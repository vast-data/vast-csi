#include "write_buffer.hpp"
#include "name_content_block.hpp"
#include "data_content_block.hpp"

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
        return wb_header->md_offset;
    }
    PT_DEBUG(DATA, "write buffer is out of space md_offset=%lu data_offset=%lu",
             wb_header->md_offset, wb_header->data_offset);
    return UINT64_MAX;
}

uint64_t WBHeaderBlock::alloc_data_chunk(uint64_t len)
{
    WBHeader *wb_header = get_wb_header();
    if (wb_header->data_offset - len > wb_header->md_offset) {
        wb_header->data_offset -= len;
        return wb_header->data_offset;
    }
    PT_DEBUG(DATA, "write buffer is out of space md_offset=%lu data_offset=%lu",
             wb_header->md_offset, wb_header->data_offset);
    return UINT64_MAX;
}

void WriteBuffer::init(EStoreIO *eio, LAddress wb_addr)
{
    _eio = eio;
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

EStoreRes WARN_UNUSED WriteBuffer::move_to_migrate_state()
{
    PT_INFO(DATA, "moving to migrate state");
    BuffersGuard buffers_guard(_eio, 1);

    // TODO lock ?
    WBHeaderBlock header_block;
    header_block.init(buffers_guard.get_next());

    EStoreRes res = read_md_header(&buffers_guard, &header_block);
    PT_RETURN(res != OK, res, "read_md_header failed");
    header_block.move_to_migrate_state();

    res = _eio->write_md(_wb_addr, header_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write header addr=0x%lx", _wb_addr.as_number());

    return OK;
}

EStoreRes WriteBuffer::alloc_md_block(BuffersGuard *buffers_guard, LAddress *addr)
{
    return alloc_md_internal(buffers_guard, WBHeader::MDType::MD_BLOCK, addr);
}

EStoreRes WARN_UNUSED WriteBuffer::alloc_md_internal(BuffersGuard *buffers_guard, WBHeader::MDType type, LAddress *addr)
{
    // TODO lock
    WBHeaderBlock header_block;
    EStoreRes res = read_md_header(buffers_guard, &header_block);
    PT_RETURN(res != OK, res, "read_md_header failed");

    *addr = _wb_addr;
    uint64_t offset = header_block.alloc_md(type);
    if (offset == UINT64_MAX) {
        // TODO need to move to the next write buffer
        PANIC("not implemented");
    }
    addr->offset += offset;
    res = _eio->write_md(_wb_addr, header_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write header block addr=0x%lx", _wb_addr.as_number());

    return OK;
}

LAddress WriteBuffer::get_content_addr(WBHeaderBlock *header_block, WBHeader::MDType type)
{
    LAddress addr = _wb_addr;
    uint64_t content_offset = header_block->get_content_offset(type);
    if (content_offset == UINT64_MAX) {
        // TODO need to move to the next write buffer
        PANIC("not implemented");
    }
    addr.offset += content_offset;
    return addr;
}

EStoreRes WriteBuffer::append_name_content(BuffersGuard *buffers_guard, const char *name, EHandle handle, LAddress *addr)
{
    // TODO lock
    // GDB
    WBHeaderBlock header_block;
    EStoreRes res = read_md_header(buffers_guard, &header_block);
    PT_RETURN(res != OK, res, "read_md_header failed");

    *addr = get_content_addr(&header_block, WBHeader::MDType::NAME_CONTENT);

    NameContentBlock content_block;
    content_block.init(buffers_guard->get_next());

    res = _eio->read_md(*addr, content_block.get_buffer(), false, nullptr);
    PT_RETURN(res != OK, res, "failed to read content_block addr=0x%lx", addr->as_number());

    res = content_block.add_handle(name, handle);
    if (res == EStoreRes::NO_MEM) {
        // alloc a new name content block;
        res = alloc_md_internal(buffers_guard, WBHeader::MDType::NAME_CONTENT, addr);
        PT_RETURN(res != OK, res, "alloc_md_internal failed");

        PTC_DEBUG("alloc new content block addr=0x%lx", addr->as_number());
        content_block.init(content_block.get_buffer());
        res = content_block.add_handle(name, handle);
    }
    PT_RETURN(res != OK, res, "failed to add name=%s to content block addr=0x%lx", name, addr->as_number());

    res = _eio->write_md(*addr, content_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write content_block addr=0x%lx", addr->as_number());

    return OK;
}

EStoreRes WriteBuffer::append_data_content(BuffersGuard *buffers_guard, EHandle handle, uint64_t offset, uint32_t len,
                                           LAddress data_addr, LAddress *addr)
{
    // TODO try to reduce code duplication with append_name_content
    // TODO lock
    WBHeaderBlock header_block;
    EStoreRes res = read_md_header(buffers_guard, &header_block);
    PT_RETURN(res != OK, res, "read_md_header failed");

    *addr = get_content_addr(&header_block, WBHeader::MDType::DATA_CONTENT);
    DataContentBlock content_block;
    content_block.init(buffers_guard->get_next());

    res = _eio->read_md(*addr, content_block.get_buffer(), false, nullptr);
    PT_RETURN(res != OK, res, "failed to read content_block addr=0x%lx", addr->as_number());

    res = content_block.add_extent(handle, offset, len, data_addr);
    if (res == EStoreRes::NO_MEM) {
        // alloc a new content block
        PTC_DEBUG("allocating new content block for handle=0x%lx", handle);
        res = alloc_md_internal(buffers_guard, WBHeader::MDType::DATA_CONTENT, addr);
        PT_RETURN(res != OK, res, "alloc_md_internal failed");

        content_block.init(content_block.get_buffer());
        res = content_block.add_extent(handle, offset, len, data_addr);
    }
    PT_RETURN(res != OK, res, "failed to add extent offset=%lu len=%u to content block addr=0x%lx",
              offset, len, addr->as_number());

    res = _eio->write_md(*addr, content_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write content_block addr=0x%lx", addr->as_number());

    return OK;
}

EStoreRes WriteBuffer::alloc_data_chunk(BuffersGuard *buffers_guard, uint64_t len, LAddress *addr)
{
    DEBUG_ASSERT(len % IO_ALIGNMENT == 0);
    // TODO lock
    WBHeaderBlock header_block;
    EStoreRes res = read_md_header(buffers_guard, &header_block);
    PT_RETURN(res != OK, res, "read_md_header failed");

    uint64_t offset = header_block.alloc_data_chunk(len);
    if (offset == UINT64_MAX) {
        PT_INFO(DATA, "out of write buffer space");
        // TODO need to move to the next write buffer
        PANIC("not implemented");
    }
    *addr = _wb_addr;
    addr->offset += offset;

    res = _eio->write_md(_wb_addr, header_block.get_buffer());
    PT_RETURN(res != OK, res, "failed to write header addr=0x%lx", _wb_addr.as_number());

    return OK;
}

EStoreRes WriteBuffer::read_md_header(BuffersGuard *buffers_guard, WBHeaderBlock *header_block)
{
    header_block->init(buffers_guard->get_next());
    EStoreRes res = _eio->read_md(_wb_addr, header_block->get_buffer(), false, nullptr);
    PT_RETURN(res != OK, res, "failed to read wb header addr=0x%lx", _wb_addr.as_number());
    DEBUG_ASSERT(header_block->get_type() == BlockType::WRITE_BUFFER_HEADER);

    if (header_block->get_wb_state() != WBState::INGEST) {
        PT_INFO(DATA, "write buffer not in ingest state");
        return EStoreRes::NOT_IN_INGEST;
    }
    return OK;
}

}

