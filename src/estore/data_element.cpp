#include <plasma/utils/io.hpp>
#include "data_element.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;
using EStoreRes::EXIST;
using P::ShardId;
using P::IO::IOVec;
using P::IO::IOVecs;


void DataElement::init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table, BuffersGuard *buffers_guard)
{
    Element::init(eio, shard_md, handles_table, buffers_guard);
    _range_block.init(_buffers_guard->get_next());
    _bitmap_block.init(_buffers_guard->get_next());
    _content_block.init(_buffers_guard->get_next());
}

EStoreRes DataElement::io_start(EHandle handle, UNUSED uint64_t offset)
{
    EStoreRes res = read_handle_block(handle);
    PT_RETURN(res != OK, res, "failed to read handle=0x%lx block", handle);

    if (!_handle_block.is_data_element()) {
        PT_ERROR(DATA, "element 0x%lx is not allowed to store data", handle);
        return EStoreRes::NOT_A_DATA_ELEMENT;
    }

    // TODO locks
    LAddress range_addr = _handle_block.get_ranges_addr();
    res = read_block(range_addr, handle, &_range_block);
    PT_RETURN(res != OK, res, "failed to read range block addr=0x%lx", range_addr.as_number());
    return OK;
}

P::ShardId DataElement::resolve_shard_id(EHandle handle, uint64_t offset) const
{
    return _handles_table->handle_to_shard_id(handle) + (offset / DATA_RANGE_SHARD_SIZE) % _eio->get_shard_count();
}

EStoreRes DataElement::add_data_bitmap_block(WriteBuffer *write_buffer, LAddress range_addr, LAddress *bitmap_addr,
                                             uint64_t offset, bool *range_updated)
{
    if (bitmap_addr->addr_type != LAddrType::NONE) {
        // TODO if bitmap block is not on the current write buffer we need to create a new one
        return OK;
    }
    uint64_t base_offset = (offset / DATA_RANGE_SHARD_SIZE) * DATA_RANGE_SHARD_SIZE;
    // need to create a new bitmap block, try to do it in the composite block
    PTC_DEBUG("need to create a bitmap block for handle=0x%lx base_offset=%lu offset=%lu",
              get_handle(), base_offset, offset);

    if (base_offset == 0) {
        // the first bitmap is contained in the handle composite block
        bitmap_addr->addr_type = LAddrType::CONTAINED;
    } else {
        EStoreRes res = write_buffer->alloc_md_block(_buffers_guard, bitmap_addr);
        PT_RETURN(res != OK, res, "alloc_internal failed handle=0x%lx offset=%lu", get_handle(), offset);
        PTC_DEBUG("new bitmap block address=0x%lx", bitmap_addr->as_number());
        _bitmap_block.init(_bitmap_block.get_buffer());
    }
    _bitmap_block.set_base_offset(base_offset);

    if (range_addr.addr_type == LAddrType::CONTAINED) {
        _range_block.replace_buffer(_buffers_guard->get_next());
    }
    EStoreRes res = _range_block.add_range(base_offset, *bitmap_addr);
    // TODO handle range block full outside of the composite block
    PT_RETURN(res != OK, res, "add_range failed to handle=0x%lx offset=%lu", get_handle(), offset);
    *range_updated = true;
    return OK;
}

EStoreRes DataElement::write_data(WriteBuffer *write_buffer, uint64_t data_len, uint64_t offset, IOVecs *io_vecs,
                                  LAddress bitmap_addr)
{
    DEBUG_ASSERT_OP(data_len, ==, io_vecs->total_length());

    // align write to allowed IO size (only the first and last might be unaligned) first io_vec might also be unaligned
    void *unaligned_base = io_vecs->iovecs[0].iov_base;
    io_vecs->iovecs[0].iov_base = (void *)IO_ALIGN_DOWN((size_t)io_vecs->iovecs[0].iov_base);
    uint64_t align_delta = (size_t)unaligned_base - (size_t)io_vecs->iovecs[0].iov_base;
    io_vecs->iovecs[0].iov_len = IO_ALIGN_UP(io_vecs->iovecs[0].iov_len + align_delta);
    io_vecs->iovecs[io_vecs->count - 1].iov_len = IO_ALIGN_UP(io_vecs->iovecs[io_vecs->count - 1].iov_len);

    EHandle handle = get_handle();
    LAddress data_addr;
    LAddress content_addr;
    uint16_t extent_index;
    uint64_t write_len = io_vecs->total_length();
    // TODO write short data (less than 512) bytes inline to the content block
    EStoreRes res = write_buffer->alloc_data_chunk(_buffers_guard, write_len, &data_addr, &content_addr, &extent_index);
    PT_RETURN(res != OK, res, "failed to allocate data chunk handle=0x%lx write_len=%lu", handle, write_len);

    PTC_DEBUG("writing data handle=0x%lx addr=0x%lx data_len=%lu", handle, data_addr.as_number(), write_len);
    res = _eio->write_data(data_addr, io_vecs);
    PT_RETURN(res != OK, res, "write_data failed handle=0x%lx addr=0x%lx write_len=%lu",
              handle, data_addr.as_number(), write_len);

    // update content block
    data_addr.offset += align_delta;
    res = write_buffer->set_data_content(_buffers_guard, content_addr, extent_index, handle, offset, data_len, data_addr);
    PT_RETURN(res != OK, res, "append_data_content failed handle=0x%lx addr=0x%lx data_len=%lu",
              handle, data_addr.as_number(), data_len);

    // TODO if the extent can be internally merged there is no need to replace the buffer and add it again to the
    // composite block
    if (bitmap_addr.addr_type == LAddrType::CONTAINED) {
        _bitmap_block.replace_buffer(_buffers_guard->get_next());
    }
    res = _bitmap_block.add_extent(offset, data_len, content_addr);
    // TODO handle bitmap being out of space
    PT_RETURN(res != OK, res, "add_extent failed handle=0x&lx offset=%lu offset=%lu data_len=%lu addr=0x%lx",
              handle, offset, data_len, content_addr.as_number());

    return OK;

}

void DataElement::update_element_size(uint64_t offset, uint64_t len)
{
    if (offset + len > get_attr()->size) {
        get_attr()->size = offset + len;
    }
}

EStoreRes DataElement::write(EHandle handle, uint64_t offset, IOVecs *io_vecs, uint64_t data_len)
{
    PT_INFO(DATA, "write handle=0x%lx offset=%lu len=%lu", handle, offset, data_len);

    bool range_updated = false;
    LAddress range_addr = _handle_block.get_ranges_addr();
    if (range_addr.addr_type == LAddrType::NONE) {
        PTC_DEBUG("need to create a range block for handle=0x%lx", handle);
        // need to create a range block, try to do it in the composite block
        range_addr.addr_type = LAddrType::CONTAINED;
        _handle_block.set_ranges_addr(range_addr);
        range_updated = true;
    }

    uint64_t write_len = data_len;
    uint64_t write_offset = offset;
    while (write_len > 0) {
        // writes might be broken between multiple bitmap blocks / shards. The range block returns the length that
        // can be written to the bitmap with the current offset. Note: that write are also split at the
        // DATA_RANGE_SHARD_SIZE even if there is still room in the bitmap block.
        uint64_t range_len = write_len;
        LAddress bitmap_addr = _range_block.get_range(write_offset, &range_len);
        PTC_DEBUG("bitmap_addr=0x%lx write_offset=%lu data_len=%lu range_len=%lu", bitmap_addr.as_number(),
                  write_offset, data_len, range_len);
        EStoreRes res = read_block(bitmap_addr, handle, &_bitmap_block);
        PT_RETURN(res != OK, res, "failed to read bitmap block addr=0x%lx", bitmap_addr.as_number());

        IOVec write_vec[io_vecs->count];
        IOVecs write_vecs = { .iovecs = io_vecs->iovecs, .count = io_vecs->count };
        // fix the write vec according to the current range we are about to write
        if (range_len != data_len) {
            uint64_t offset_delta = write_offset - offset;
            uint64_t vec_idx = offset_delta / DATA_BUFFER_SIZE;
            write_vecs.iovecs = write_vec;
            write_vecs.count = 1;
            write_vec[0].iov_base = (char *)io_vecs->iovecs[vec_idx].iov_base + (offset_delta % DATA_BUFFER_SIZE);
            write_vec[0].iov_len = io_vecs->iovecs[vec_idx].iov_len - (offset_delta % DATA_BUFFER_SIZE);
            write_vec[0].iov_len = P_MIN(write_vec[0].iov_len, range_len);
            uint64_t remaining_len = range_len - write_vec[0].iov_len;
            for (int i = 1; remaining_len > 0; ++i) {
                write_vec[i].iov_base = io_vecs->iovecs[vec_idx + i].iov_base;
                write_vec[i].iov_len = P_MIN(io_vecs->iovecs[vec_idx + i].iov_len, remaining_len);
                remaining_len -= write_vec[i].iov_len;
                ++write_vecs.count;
            }
        }

        write_len -= range_len;
        ShardId shard_id = resolve_shard_id(handle, write_offset);
        PTC_DEBUG("handle=0x%lx offset=%lu shard_id=%hu", handle, write_offset, shard_id);
        WriteBuffer *write_buffer = _shard_md->get_ingest_buffer(shard_id);

        res = add_data_bitmap_block(write_buffer, range_addr, &bitmap_addr, write_offset, &range_updated);
        PT_RETURN(res != OK, res, "add_data_bitmap_block failed handle=0x%lx", handle);

        res = write_data(write_buffer, range_len, write_offset, &write_vecs, bitmap_addr);
        PT_RETURN(res != OK, res, "write_data failed handle=0x%lx range_len=%lu", handle, range_len);
        write_offset += range_len;

        // TODO review the correct write order of the blocks and verify it complies with the design of the bad path
        if (bitmap_addr.addr_type == LAddrType::MD_BLOCKS || bitmap_addr.addr_type == LAddrType::WRITE_BUFFER) {
            res = _eio->write_md(bitmap_addr, _bitmap_block.get_buffer());
            PT_RETURN(res != OK, res, "_eio->write_md failed addr=0x%lx", bitmap_addr.as_number());
        }
        if (bitmap_addr.addr_type == LAddrType::CONTAINED) {
            PTC_DEBUG("updating contained bitmap block");
            res = _composite_block.replace_contained_block(handle, &_bitmap_block);
            // TODO handle composite block being out of space
            PT_RETURN(res != OK, res, "replace_contained_block for bitmap block failed handle=0x%lx", handle);
        }
    }

    update_mc_times();
    update_element_size(offset, data_len);

    if (range_updated && range_addr.addr_type == LAddrType::CONTAINED) {
        EStoreRes res = _composite_block.replace_contained_block(handle, &_range_block);
        if (res != OK) {
            _composite_block.trace_contained_blocks("out of space during write");
        }
        // TODO handle composite block being out of space
        PT_RETURN(res != OK, res, "replace_contained_block for range block failed handle=0x%lx", handle);
    }

    // write range and handle blocks
    // TODO deal with handle block being outside of composite
    // TODO don't always update table
    EStoreRes res = _handles_table->write(handle, _composite_block.get_buffer());
    PT_RETURN(res != OK, res, "_handles_table->write failed parent=0x%lx", handle);

    if (range_updated && range_addr.addr_type == LAddrType::MD_BLOCKS) {
        res = _eio->write_md(range_addr, _range_block.get_buffer());
        PT_RETURN(res != OK, res, "_eio->write_md failed addr=0x%lx", range_addr.as_number());
    }

    return OK;
}

uint32_t DataElement::fill_hole(uint64_t prev_offset, uint64_t extent_offset, IOVecs *res_vecs, IOVecs *alloc_vecs,
                                uint32_t n_buffers, uint32_t max_results, uint16_t *curr_buffer, uint32_t *buffer_offset)
{
    uint32_t bytes_filled = 0;
    uint64_t hole_len = extent_offset - prev_offset;
    while (hole_len > 0 && n_buffers > *curr_buffer && res_vecs->count < max_results) {
        res_vecs->iovecs[res_vecs->count].iov_base = (char *)alloc_vecs->iovecs[*curr_buffer].iov_base + *buffer_offset;
        res_vecs->iovecs[res_vecs->count].iov_len = P_MIN(hole_len, DATA_BUFFER_SIZE - *buffer_offset);
        memset(res_vecs->iovecs[res_vecs->count].iov_base, 0, res_vecs->iovecs[res_vecs->count].iov_len);
        hole_len -= res_vecs->iovecs[res_vecs->count].iov_len;
        *buffer_offset += res_vecs->iovecs[res_vecs->count].iov_len;
        bytes_filled += res_vecs->iovecs[res_vecs->count].iov_len;
        res_vecs->count++;
        if (*buffer_offset >= DATA_BUFFER_SIZE) {
            *buffer_offset = 0;
            (*curr_buffer)++;
        }
    }
    PTC_DEBUG("extent_offset=%lu prev_offset=%lu bytes_filled=%u", extent_offset, prev_offset, bytes_filled);
    return bytes_filled;
}

EStoreRes DataElement::read_content_addrs(uint64_t offset, uint32_t len)
{
    _n_content_addrs = 0;
    uint64_t read_len = len;
    uint64_t read_offset = offset;
    MIOBuffer *bitmap_buff = _buffers_guard->get_next();
    while (read_len > 0) {
        // reads might be broken between multiple bitmap blocks / shards.
        uint64_t range_len = read_len;
        LAddress bitmap_addr = _range_block.get_range(read_offset, &range_len);
        PTC_DEBUG("bitmap_addr=0x%lx read_offset=%lu len=%u range_len=%lu", bitmap_addr.as_number(),
                  read_offset, len, range_len);
        DEBUG_ASSERT(range_len <= DATA_RANGE_SHARD_SIZE);
        if (bitmap_addr.addr_type != Layout::AddrType::NONE) {
            _bitmap_block.init(bitmap_buff);
            EStoreRes res = read_block(bitmap_addr, get_handle(), &_bitmap_block);
            PT_RETURN(res != OK, res, "failed to read bitmap block addr=0x%lx", bitmap_addr.as_number());

            // get content blocks that contain relevant extents
            uint16_t res_content_addrs = MAX_ADDR_PER_READ - _n_content_addrs;
            res = _bitmap_block.get_content_addrs(read_offset, read_len, &res_content_addrs,
                                                  &_content_addrs[_n_content_addrs]);
            // TODO handle the case in which there are more than n_content_addrs
            PT_RETURN(res != OK, res, "get_content_addrs failed handle=0x%lx offset=%lu len=%u", get_handle(), offset,
                      len);

            _n_content_addrs += res_content_addrs;
        }
        read_len -= range_len;
        read_offset += range_len;
    }
    PTC_DEBUG("n_content_addrs=%hu", _n_content_addrs);
    return OK;
}

EStoreRes DataElement::read(uint64_t offset, uint32_t len, IOVecs *res_vecs, IOVecs *alloc_vecs,
                            uint32_t *bytes_read, bool *eof)
{
    *eof = false;
    *bytes_read = 0;

    if (offset  >= _handle_block.get_attr()->size) {
        len = 0;
    } else if (offset + len >= _handle_block.get_attr()->size) {
        len = _handle_block.get_attr()->size - offset;
        // not setting eof here since we might be not be able to read all the requested data
    }
    if (len == 0) {
        if (offset >= _handle_block.get_attr()->size) {
            *eof = true;
        }
        PTC_DEBUG("zero length read offset=%lu element_size=%lu", offset, _handle_block.get_attr()->size);
        res_vecs->count = 0;
        alloc_vecs->count = 0;
        return OK;
    }

    EHandle handle = get_handle();
    // build the extents list that composes the read
    EStoreRes res = read_content_addrs(offset, len);
    PT_RETURN(res != OK, res, "read_content_addrs failed handle=0x%lx", handle);
    res = read_extents(offset, len);
    PT_RETURN(res != OK, res, "read_extents failed handle=0x%lx", handle);

    // allocate data buffers, keep spare for 2 IO_ALIGNMENT (thou there might be more)
    uint32_t n_buffers = ((len + (2 * IO_ALIGNMENT)) / DATA_BUFFER_SIZE) + (len % DATA_BUFFER_SIZE ? 1 : 0);
    ASSERT_OP(n_buffers, <=, res_vecs->count);
    alloc_vecs->count = n_buffers;
    alloc_vecs->iovecs = res_vecs->iovecs;
    _eio->alloc_data_buffers(alloc_vecs);
    PT_RETURN(alloc_vecs->count < n_buffers, EStoreRes::NO_MEM,
              "alloc_data_buffers failed handle=0x%lx n_buffers=%u allocated_buffers=%u",
              handle, n_buffers, alloc_vecs->count);

    res = read_data(offset, len, res_vecs, alloc_vecs, bytes_read);
    PT_RETURN(res != OK, res, "read data failed");


    if (offset + (*bytes_read) >= _handle_block.get_attr()->size) {
        *eof = true;
    }

    return OK;
}

EStoreRes DataElement::read_extents(uint64_t offset, uint32_t len)
{
    EHandle handle = get_handle();
    // feed the extents into the extents container which deals internally with data overwrites and aligns the
    // extents to the extent being read
    _extents_container.init(offset, len);
    LOOP(_n_content_addrs, i) {
        _content_block.init(_content_block.get_buffer());
        EStoreRes res = _eio->read_md(_content_addrs[i], _content_block.get_buffer());
        PT_RETURN(res != OK, res, "read_md failed handle=0x%lx addr=0x%lx", handle, _content_addrs[i].as_number());

        res = _content_block.export_extents(handle, offset, len, &_extents_container);
        //  TODO handle the case in which the extents_container is out of space (push out extents with higher offset)
        PT_RETURN(res != OK, res, "get_extents failed handle=0x%lx offset=%lu len=%u", handle, offset, len);
    }

    return OK;
}

EStoreRes DataElement::read_data(uint64_t offset, uint32_t len, P::IO::IOVecs *res_vecs, P::IO::IOVecs *alloc_vecs,
                                 uint32_t *bytes_read)
{
    EHandle handle = get_handle();
    uint32_t n_buffers = alloc_vecs->count;
    // the first part of the res vector is taken by the allocated buffers
    const uint32_t max_results = res_vecs->count - alloc_vecs->count;
    res_vecs->iovecs = &alloc_vecs->iovecs[alloc_vecs->count];
    // vectors used for reading the data in an aligned manner
    DEBUG_ASSERT_OP(max_results, <=, (MAX_IO_SIZE / DATA_BUFFER_SIZE) + 1)
    DEBUG_ASSERT_OP(max_results, >, 0)

    IOVec read_vec[max_results];
    IOVecs read_vecs[max_results];
    uint16_t curr_read_vec = 0;
    uint16_t curr_read_vecs = 0;

    uint16_t curr_buffer = 0;
    uint32_t buffer_offset = 0;
    res_vecs->count = 0;

    // read the extents
    uint64_t prev_offset = offset;
    // since reads must be aligned both on disk and in memory we need to manage 3 iovecs. one for the memory we use
    // (alloc_vecs) the second for the read operations (read_vec) and the last for the data we return (res_vecs).
    for (DataExtent *extent = _extents_container.get_next(nullptr);
         extent != nullptr && curr_buffer < n_buffers && res_vecs->count < max_results;
         extent = _extents_container.get_next(extent))
    {
        if (prev_offset < extent->_offset) {
            // we got a hole, need to fill the result buffer with zeros
            *bytes_read += fill_hole(prev_offset, extent->_offset, res_vecs, alloc_vecs, n_buffers, max_results,
                                     &curr_buffer, &buffer_offset);
        }
        prev_offset = extent->_offset + extent->_len;

        read_vecs[curr_read_vecs].iovecs = &read_vec[curr_read_vec];
        read_vecs[curr_read_vecs].count = 0;
        // align read offset
        LAddress read_addr = extent->_data_addr;
        read_addr.offset = IO_ALIGN_DOWN(read_addr.offset);
        uint64_t offset_diff = extent->_data_addr.offset - read_addr.offset;
        while (extent->_len > 0 && curr_buffer < n_buffers && res_vecs->count < max_results && curr_read_vec < max_results) {
            DEBUG_ASSERT(curr_buffer < n_buffers);
            read_vec[curr_read_vec].iov_base = (char *)alloc_vecs->iovecs[curr_buffer].iov_base + buffer_offset;
            res_vecs->iovecs[res_vecs->count].iov_base = (char *)read_vec[curr_read_vec].iov_base + offset_diff;
            uint32_t read_len = P_MIN(extent->_len, DATA_BUFFER_SIZE - buffer_offset);
            read_vec[curr_read_vec].iov_len = IO_ALIGN_UP(read_len + offset_diff);
            // the size relevant to the user is the min value between what he asked to read and what we are going to read
            uint32_t res_vec_len = P_MIN(read_vec[curr_read_vec].iov_len - offset_diff, extent->_len);
            res_vecs->iovecs[res_vecs->count].iov_len = res_vec_len;
            PTC_DEBUG("extent->_len=%u read_len=%u res_vec_len=%u buffer_offset=%u iov_len=%lu",
                      extent->_len, read_len, res_vec_len, buffer_offset, read_vec[curr_read_vec].iov_len);
            buffer_offset += read_vec[curr_read_vec].iov_len;
            read_vecs[curr_read_vecs].count++;
            res_vecs->count++;
            curr_read_vec++;
            // TODO check if res can be merged with the prev one
            extent->_len -= res_vec_len;
            if (buffer_offset >= DATA_BUFFER_SIZE) {
                buffer_offset = 0;
                curr_buffer++;
            }
            (*bytes_read) += res_vec_len;
            // offset_diff applies only for the first item in the vector
            offset_diff = 0;
        }

        // TODO pass a future and do async reads
        EStoreRes res = _eio->read_data(read_addr, &read_vecs[curr_read_vecs], nullptr);
        PT_RETURN(res != OK, res, "read_data failed handle=0x%lx offset=%lu len=%u", handle, offset, len);
        curr_read_vecs++;
    }

    if (prev_offset < offset + len) {
        // fill the leftovers with zeros
        *bytes_read += fill_hole(prev_offset, offset + len, res_vecs, alloc_vecs, n_buffers, max_results,
                                 &curr_buffer, &buffer_offset);
    }

    return OK;
}

struct TruncateCtx {
    DataElement *element;
    uint64_t size;
};

static EStoreRes truncate_cb_func(Layout::Address addr, uint64_t offset, void *ctx)
{
    TruncateCtx *truncate_ctx = (TruncateCtx *)ctx;
    return truncate_ctx->element->truncate_cb(addr, offset, ctx);
}


EStoreRes DataElement::truncate_cb(Layout::Address addr, UNUSED uint64_t offset, void *ctx)
{
    TruncateCtx *truncate_ctx = (TruncateCtx *)ctx;
    EStoreRes res = read_block(addr, get_handle(), &_bitmap_block);
    PT_RETURN(res != OK, res, "read_block failed handle=0x%lx addr=0x%lx", get_handle(), addr.as_number());

    if (addr.addr_type == LAddrType::CONTAINED) {
        _bitmap_block.replace_buffer(_buffers_guard->get_next());
    }
    _bitmap_block.truncate(truncate_ctx->size);
    if (addr.addr_type == LAddrType::MD_BLOCKS || addr.addr_type == LAddrType::WRITE_BUFFER) {
        res = _eio->write_md(addr, _bitmap_block.get_buffer());
        PT_RETURN(res != OK, res, "_eio->write_md failed addr=0x%lx", addr.as_number());
    }

    return OK;
}

EStoreRes DataElement::truncate(uint64_t size)
{
    EHandle handle = get_handle();
    if (size == get_attr()->size || get_attr()->size == 0) {
        PTC_INFO("ignoring truncate of zero sized element handle=0x%lx new_size=%lu", handle, size);
        return OK;
    }
    PTC_INFO("truncate handle=0x%lx current_size=%lu new_size=%lu", handle, get_attr()->size, size);

    // Note: the current implementation updates all of the element bitmap blocks. A more efficient implementation can be
    // to mark something in the range block instead. Making such a mark requires adding the notion of time to writes
    // so it should be added once snapshot support is implemented.
    // TODO locks, support multiple range blocks
    LAddress range_addr = _handle_block.get_ranges_addr();
    EStoreRes res = read_block(range_addr, handle, &_range_block);
    PT_RETURN(res != OK, res, "failed to read range block addr=0x%lx", range_addr.as_number());

    TruncateCtx truncate_ctx = {
        .element = this,
        .size = size,
    };
    res = _range_block.traverse(size, truncate_cb_func, &truncate_ctx);
    PT_RETURN(res != OK, res, "traverse failed");

    // truncate is call from set attr so the element size and handle block will be updated from it
    return OK;
}

}
