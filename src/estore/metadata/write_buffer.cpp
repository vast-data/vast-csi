#include <estore/defs/estore_defs.hpp>
#include "write_buffer.hpp"
#include "name_content_block.hpp"
#include "data_content_block.hpp"
#include "shard_md.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;

void WBHeaderBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::WRITE_BUFFER_HEADER);
    set_version(INITIAL_BLOCK_VER);
    ASSERT(space_left() >= sizeof(WBHeader));
    add_used_bytes(sizeof(WBHeader));
}

void WBHeaderBlock::reset()
{
    WBHeader *wb_header = get_wb_header();
    wb_header->name_content_offset = 0;
    wb_header->data_content_offset = 0;
    wb_header->md_offset = 0;
    wb_header->data_offset = WRITE_BUFFER_SIZE;
    wb_header->state = WBState::INGEST;
}

uint64_t WBHeaderBlock::alloc_md(WBHeader::MDType type)
{
    WBHeader *wb_header = get_wb_header();
    uint64_t offset = alloc_internal();
    switch (type) {
        case WBHeader::MDType::NAME_CONTENT:
            wb_header->name_content_offset = offset;
            break;
        case WBHeader::MDType::DATA_CONTENT:
            wb_header->data_content_offset = offset;
            break;
        case WBHeader::MDType::MD_BLOCK:
            break;
    }
    return offset;
}

uint64_t WBHeaderBlock::alloc_internal()
{
    WBHeader *wb_header = get_wb_header();
    if (wb_header->md_offset + NVRAM_MD_BLOCK_SIZE < wb_header->data_offset) {
        wb_header->md_offset += NVRAM_MD_BLOCK_SIZE;
        DEBUG_ASSERT(wb_header->md_offset  <= WRITE_BUFFER_SIZE);
        return wb_header->md_offset;
    }
    PT_DEBUG(DATA, "write buffer is out of space md_offset=%lu data_offset=%lu",
             wb_header->md_offset, wb_header->data_offset);
    return UINT64_MAX;
}

uint64_t WBHeaderBlock::alloc_data_chunk(uint64_t len)
{
    WBHeader *wb_header = get_wb_header();
    if (wb_header->data_offset > len && wb_header->data_offset - len > wb_header->md_offset) {
        wb_header->data_offset -= len;
        DEBUG_ASSERT(wb_header->data_offset <= WRITE_BUFFER_SIZE);
        return wb_header->data_offset;
    }
    PT_DEBUG(DATA, "write buffer is out of space md_offset=%lu data_offset=%lu",
             wb_header->md_offset, wb_header->data_offset);
    return UINT64_MAX;
}

void WriteBuffer::init(EStoreIO *eio, ShardMd *shard_md, P::ShardId shard_id, LAddress wb_addr)
{
    _eio = eio;
    _shard_md = shard_md;
    _shard_id = shard_id;
    _wb_addr = wb_addr;
}

EStoreRes WriteBuffer::reset()
{
    BuffersGuard buffers_guard(_eio, 3);

    WBHeaderBlock header_block;
    header_block.init(buffers_guard.get_next());
    header_block.reset();

    NameContentBlock name_content_block;
    name_content_block.init(buffers_guard.get_next());
    LAddress addr = _wb_addr;
    addr.offset += header_block.alloc_md(WBHeader::MDType::NAME_CONTENT);
    EStoreRes res = _eio->write_md(addr, name_content_block.get_buffer());
    PT_RETURN(res != OK, res, "write_md failed addr=0x%lx", addr.as_number());

    DataContentBlock data_content_block;
    data_content_block.init(buffers_guard.get_next());
    addr = _wb_addr;
    addr.offset += header_block.alloc_md(WBHeader::MDType::DATA_CONTENT);
    res = _eio->write_md(addr, data_content_block.get_buffer());
    PT_RETURN(res != OK, res, "write_md failed addr=0x%lx", addr.as_number());

    res = _eio->write_md(_wb_addr, header_block.get_buffer());
    PT_RETURN(res != OK, res, "write_md failed addr=0x%lx", _wb_addr.as_number());

    return OK;
}

EStoreRes WriteBuffer::alloc_md_block(BuffersGuard *buffers_guard, LAddress *addr)
{
    // TODO lock
    WBHeaderBlock header_block;
    header_block.init(buffers_guard->get_next());

    do {
        EStoreRes res = read_md_header(buffers_guard, &header_block);
        PT_RETURN(res != OK, res, "read_md_header failed");

        res = alloc_md_internal(&header_block, WBHeader::MDType::MD_BLOCK, addr);
        if (res == EStoreRes::WRITE_BUFFER_FULL) {
            res = move_to_next_ingest_buffer(buffers_guard, &header_block);
            PT_RETURN(res != OK, res, "move_to_next_ingest_buffer failed");
            continue;
        }
        PT_RETURN(res != OK, res, "alloc_md_internal failed");

        break;
    } while (true);

    EStoreRes res = _eio->write_md(_wb_addr, header_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write header block addr=0x%lx", _wb_addr.as_number());
    return OK;
}

EStoreRes WriteBuffer::alloc_md_internal(WBHeaderBlock *header_block, WBHeader::MDType type, LAddress *addr)
{
    *addr = _wb_addr;
    uint64_t offset = header_block->alloc_md(type);
    if (offset == UINT64_MAX) {
        return EStoreRes::WRITE_BUFFER_FULL;
    }
    addr->offset += offset;

    return OK;
}

EStoreRes WriteBuffer::get_content_addr(WBHeaderBlock *header_block, WBHeader::MDType type, LAddress *addr)
{
    *addr = _wb_addr;
    uint64_t content_offset = header_block->get_content_offset(type);
    if (content_offset == UINT64_MAX) {
        return EStoreRes::WRITE_BUFFER_FULL;
    }
    addr->offset += content_offset;
    return OK;
}

EStoreRes WriteBuffer::append_name_content(BuffersGuard *buffers_guard, EHandle parent, const char *name,
                                           EHandle handle, LAddress *addr)
{
    // TODO lock
    WBHeaderBlock header_block;
    header_block.init(buffers_guard->get_next());
    NameContentBlock content_block;
    content_block.init(buffers_guard->get_next());

    do {
        EStoreRes res = read_md_header(buffers_guard, &header_block);
        PT_RETURN(res != OK, res, "read_md_header failed");

        res = get_content_addr(&header_block, WBHeader::MDType::NAME_CONTENT, addr);
        if (res == EStoreRes::WRITE_BUFFER_FULL) {
            res = move_to_next_ingest_buffer(buffers_guard, &header_block);
            PT_RETURN(res != OK, res, "move_to_next_ingest_buffer failed");
            continue;
        }

        PT_RETURN(res != OK, res, "read_md_header failed");

        res = _eio->read_md(*addr, content_block.get_buffer(), false, nullptr);
        PT_RETURN(res != OK, res, "failed to read content_block addr=0x%lx", addr->as_number());

        res = content_block.add_handle(parent, name, handle);
        if (res == EStoreRes::NO_MEM) {
            // alloc a new name content block;
            res = alloc_md_internal(&header_block, WBHeader::MDType::NAME_CONTENT, addr);
            if (res == EStoreRes::WRITE_BUFFER_FULL) {
                res = move_to_next_ingest_buffer(buffers_guard, &header_block);
                PT_RETURN(res != OK, res, "move_to_next_ingest_buffer failed");
                continue;
            }
            PT_RETURN(res != OK, res, "alloc_md_internal failed");

            res = _eio->write_md(_wb_addr, header_block.get_buffer());
            PT_RETURN(res != OK, res, "failed to write header block addr=0x%lx", _wb_addr.as_number());

            PTC_DEBUG("alloc new content block addr=0x%lx", addr->as_number());
            content_block.init(content_block.get_buffer());
            res = content_block.add_handle(parent, name, handle);
        }
        PT_RETURN(res != OK, res, "failed to add name=%s to content block addr=0x%lx", name, addr->as_number());

        break;
    } while (true);

    EStoreRes res = _eio->write_md(*addr, content_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write content_block addr=0x%lx", addr->as_number());

    return OK;
}

EStoreRes WriteBuffer::set_data_content(BuffersGuard *buffers_guard, LAddress content_addr, uint16_t extent_index,
                                        EHandle handle, uint64_t offset, uint32_t len, LAddress data_addr)
{
    PTC_DEBUG("content_addr=0x%lx extent_index=%u", content_addr.as_number(), extent_index);
    // TODO lock
    DataContentBlock content_block;
    content_block.init(buffers_guard->get_next());

    EStoreRes res = _eio->read_md(content_addr, content_block.get_buffer(), false, nullptr);
    PT_RETURN(res != OK, res, "failed to read content_block addr=0x%lx", content_addr.as_number());

    content_block.set_extent(extent_index, handle, offset, len, data_addr);

    res = _eio->write_md(content_addr, content_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write content_block addr=0x%lx", content_addr.as_number());

    return OK;
}

EStoreRes WriteBuffer::alloc_data_chunk(BuffersGuard *buffers_guard, uint64_t len, LAddress *data_addr,
                                        LAddress *content_addr, uint16_t *extent_index)
{
    DEBUG_ASSERT(len % IO_ALIGNMENT == 0);
    // TODO lock (lock should be global for all ingest write buffers)
    WBHeaderBlock header_block;
    header_block.init(buffers_guard->get_next());
    DataContentBlock content_block;
    content_block.init(buffers_guard->get_next());
    do {
        EStoreRes res = read_md_header(buffers_guard, &header_block);
        PT_RETURN(res != OK, res, "read_md_header failed");

        uint64_t offset = header_block.alloc_data_chunk(len);
        if (offset == UINT64_MAX) {
            res = move_to_next_ingest_buffer(buffers_guard, &header_block);
            PT_RETURN(res != OK, res, "move_to_next_ingest_buffer failed");
            continue;
        }
        *data_addr = _wb_addr;
        data_addr->offset += offset;

        res = get_content_addr(&header_block, WBHeader::MDType::DATA_CONTENT, content_addr);
        if (res == EStoreRes::WRITE_BUFFER_FULL) {
            res = move_to_next_ingest_buffer(buffers_guard, &header_block);
            PT_RETURN(res != OK, res, "move_to_next_ingest_buffer failed");
            continue;
        }
        PT_RETURN(res != OK, res, "get_content_addr failed");

        res = _eio->read_md(*content_addr, content_block.get_buffer(), false, nullptr);
        PT_RETURN(res != OK, res, "failed to read content_block addr=0x%lx", content_addr->as_number());

        res = content_block.alloc_extent(extent_index);
        if (res == EStoreRes::NO_MEM) {
            // alloc a new content block
            PTC_DEBUG("allocating new content block");
            res = alloc_md_internal(&header_block, WBHeader::MDType::DATA_CONTENT, content_addr);
            if (res == EStoreRes::WRITE_BUFFER_FULL) {
                res = move_to_next_ingest_buffer(buffers_guard, &header_block);
                PT_RETURN(res != OK, res, "move_to_next_ingest_buffer failed");
                continue;
            }
            PT_RETURN(res != OK, res, "alloc_md_internal failed");

            content_block.init(content_block.get_buffer());
            res = content_block.alloc_extent(extent_index);
        }
        PT_RETURN(res != OK, res, "failed to alloc extent");
        break;
    } while (true);

    EStoreRes res = _eio->write_md(*content_addr, content_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write content_block addr=0x%lx", content_addr->as_number());
    res = _eio->write_md(_wb_addr, header_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write header addr=0x%lx", _wb_addr.as_number());

    PTC_DEBUG("data_addr=0x%lx content_addr=0x%lx extent_index=%u", data_addr->as_number(), content_addr->as_number(),
              *extent_index);

    return OK;
}

EStoreRes WriteBuffer::read_md_header(BuffersGuard *buffers_guard, WBHeaderBlock *header_block)
{
    EStoreRes res = _eio->read_md(_wb_addr, header_block->get_buffer());
    PT_RETURN(res != OK, res, "failed to read wb header addr=0x%lx", _wb_addr.as_number());
    DEBUG_ASSERT(header_block->get_type() == BlockType::WRITE_BUFFER_HEADER);

    while (header_block->get_wb_state() != WBState::INGEST) {
        PT_INFO(DATA, "write buffer not in ingest state, updating buffer address");
        res = _shard_md->get_ingest_addr(buffers_guard, _shard_id, &_wb_addr);
        PT_RETURN(res != OK, res, "get_ingest_addr failed");
        res = _eio->read_md(_wb_addr, header_block->get_buffer(), false, nullptr);
        PT_RETURN(res != OK, res, "failed to read wb header addr=0x%lx", _wb_addr.as_number());
    }

    return OK;
}

EStoreRes WriteBuffer::move_to_next_ingest_buffer(BuffersGuard *buffers_guard, WBHeaderBlock *header_block)
{
    // TODO make sure a write buffer does not start migration while its being written into (similar to the md realloc problem)
    PT_INFO(DATA, "write buffer full, moving to next buffer shard_id=%u", _shard_id);

    header_block->move_to_migrate_state();
    EStoreRes res = _eio->write_md(_wb_addr, header_block->get_buffer());
    PT_RETURN(res != OK, res, "failed to write header addr=0x%lx", _wb_addr.as_number());

    res = _shard_md->switch_ingest_buffer(buffers_guard, _shard_id, &_wb_addr);
    PT_RETURN(res != OK, res, "switch_ingest_buffer failed");

    // TODO send notification to migrator?

    return OK;
}

EStoreRes MigrateBuffer::begin_migrate(BuffersGuard *buffers_guard)
{
    _header_block.init(buffers_guard->get_next());
    EStoreRes res = _eio->read_md(_wb_addr, _header_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to read wb header addr=0x%lx", _wb_addr.as_number());
    DEBUG_ASSERT(_header_block.get_type() == BlockType::WRITE_BUFFER_HEADER);
    ASSERT(_header_block.get_wb_state() == WBState::MIGRATE);
    _current_md_offset = 0;

    return OK;
}

EStoreRes MigrateBuffer::get_next_md_block(MIOBuffer *mio_buffer)
{
    if (_current_md_offset >= _header_block.get_md_offset()) {
        return EStoreRes::NOENT;
    }
    LAddress addr = _wb_addr;
    addr.offset += _current_md_offset;
    // TODO this can potentially be optimized by reading multiple MD blocks from the write buffer
    EStoreRes res = _eio->read_md(addr, mio_buffer);
    PT_RETURN(res != OK, res, "read_md failed addr=0x%lx", addr.as_number());
    _current_md_offset += mio_buffer->get_raw_size();

    return OK;
}

}
