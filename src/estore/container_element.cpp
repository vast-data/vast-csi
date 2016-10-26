#include "container_element.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;
using EStoreRes::EXIST;
using P::ShardId;

void ContainerElement::init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table, BuffersGuard *buffers_guard)
{
    Element::init(eio, shard_md, handles_table, buffers_guard);

    _range_block.init(_buffers_guard->get_next());
    _bitmap_block.init(_buffers_guard->get_next());
    _content_block.init(_buffers_guard->get_next());
}

EStoreRes ContainerElement::read_name_blocks(const char *name, EHandle *name_handle)
{
    // get ranges block
    EHandle handle = get_handle();
    LAddress range_addr = _handle_block.get_ranges_addr();
    EStoreRes res = read_block(range_addr, handle, &_range_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", range_addr.as_number());

    if (range_addr.addr_type == LAddrType::NONE) {
        // if the ranges block does not exist
        PTC_INFO("handle=0x%lx does not have a range block", handle);
        return EStoreRes::NOENT;
    }

    // get bitmap block
    LAddress bitmap_addr = _range_block.get_address(name);
    res = read_block(bitmap_addr, handle, &_bitmap_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", bitmap_addr.as_number());

    if (bitmap_addr.addr_type == LAddrType::NONE) {
        PTC_INFO("failed to get bitmap block handle=0x%lx", handle);
        return EStoreRes::NOENT;
    }

    // get content block addr
    LAddress content_addr;
    res = _bitmap_block.get_addr(name, &content_addr);
    if (res == EStoreRes::NOENT) {
        PTC_INFO("element not found handle=0x%lx name=%s", handle, name);
        return EStoreRes::NOENT;
    }
    PT_RETURN(res != OK, res, "failed to get content block addr name=%s", name);

    // read content block
    res = read_block(content_addr, handle, &_content_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", content_addr.as_number());

    res = _content_block.get_handle(handle, name, name_handle);
    PT_RETURN(res != OK, res, "get_handle failed name=%s", name);

    return OK;
}

EStoreRes ContainerElement::add_child(const char *name, LAddress content_addr)
{
    // TODO locks
    LAddress range_addr = _handle_block.get_ranges_addr();
    bool range_updated = false;
    if (range_addr.addr_type == LAddrType::NONE) {
        // if the ranges block does not exist attempt to add it to the handle composite block
        _handle_block.set_ranges_addr(Layout::CONTAINED_ADDRESS);
        range_updated = true;
    }

    LAddress bitmap_addr = _range_block.get_address(name);
    if (bitmap_addr.addr_type == LAddrType::NONE) {
        // if the bitmap block did not exist we'll attempt to add it to the handle composite block
        // TODO will the " " range always be first?
        EStoreRes res = _range_block.add_range(" ", Layout::CONTAINED_ADDRESS);
        PT_RETURN(res != OK, res, "add_range failed");
        range_updated = true;
    }

    if (bitmap_addr.addr_type == LAddrType::CONTAINED) {
        // bitmap block is contained within a composite block, replace its buffer so it will have space to contain new
        // names
        _bitmap_block.replace_buffer(_buffers_guard->get_next());
    }

    // add the address of the content block to the bitmap
    EStoreRes res = _bitmap_block.add_name(name, content_addr);
    PT_RETURN(res != OK && res != EStoreRes::NO_MEM, res, "failed to update bitmap block");
    if (res == EStoreRes::NO_MEM) {
        // TODO out of space in the bitmap block, need to add another one and update the range block
        PANIC("not implemented");
        range_updated = true;
    }

    EHandle handle = get_handle();
    bool update_table = false;
    if (range_updated) {
        if (range_addr.addr_type == LAddrType::CONTAINED || range_addr.addr_type == LAddrType::NONE) {
            res = _composite_block.replace_contained_block(handle, &_range_block);
            // TODO handle the case the composite block has no space
            PT_RETURN(res != OK, res, "replace_contained_block failed parent=0x%lx", handle);
            update_table = true;
        } else {
            ASSERT(range_addr.addr_type == LAddrType::MD_BLOCKS);
        }
    }

    if (bitmap_addr.addr_type == LAddrType::CONTAINED || bitmap_addr.addr_type == LAddrType::NONE) {
        res = _composite_block.replace_contained_block(handle, &_bitmap_block);
        // TODO handle the case the composite block has no space
        if (res != OK) {
            _bitmap_block.trace();
        }
        PT_RETURN(res != OK, res, "replace_contained_block failed parent=0x%lx", handle);
        update_table = true;
    } else {
        ASSERT(bitmap_addr.addr_type == LAddrType::MD_BLOCKS);
    }

    if (update_table) {
        res = _handles_table->write(handle, _composite_block.get_buffer());
        PT_RETURN(res != OK, res, "_handles_table->write failed parent=0x%lx", handle);
    }

    if (bitmap_addr.addr_type == LAddrType::MD_BLOCKS) {
        res = _eio->write_md(bitmap_addr, _bitmap_block.get_buffer());
        PT_RETURN(res != OK, res, "_eio->write failed addr=0x%lx", bitmap_addr.as_number());
    }
    if (range_updated && range_addr.addr_type == LAddrType::MD_BLOCKS) {
        res = _eio->write_md(range_addr, _range_block.get_buffer());
        PT_RETURN(res != OK, res, "_eio->write failed addr=0x%lx", range_addr.as_number());
    }

    // TODO trigger bitmap split if about to run out of space
    return OK;
}

struct ListElementsCtx {
    ContainerElement *element;
    ListCallback list_cb;
    void *caller_ctx;
    ListOffset list_offset;
    ListOffset res_offset;
    EHandle handle;
};

static EStoreRes name_content_traverse_func(const char *name, uint16_t name_len, uint32_t hash, EHandle handle, void *ctx)
{
    ListElementsCtx *list_ctx = (ListElementsCtx *)ctx;
    list_ctx->res_offset.name_hash = hash;
    ListEntry entry = {
        .handle = handle,
        .name = name,
        .name_len = name_len,
        .is_common_prefix = false,
        .offset = list_ctx->res_offset.as_number(),
    };

    bool cont = list_ctx->list_cb(&entry, list_ctx->caller_ctx);
    if (!cont) {
        return EStoreRes::STOP;
    }
    return OK;
}

static EStoreRes name_bitmap_traverse_func(Layout::LAddress addr, void *ctx)
{
    ListElementsCtx *list_elements_ctx = (ListElementsCtx *)ctx;
    return list_elements_ctx->element->name_bitmap_traverse(addr, ctx);
}

EStoreRes ContainerElement::name_bitmap_traverse(Layout::LAddress addr, void *ctx)
{
    DEBUG_ASSERT(addr.addr_type != Layout::AddrType::NONE);
    ListElementsCtx *list_ctx = (ListElementsCtx *)ctx;
    EStoreRes res = read_block(addr, list_ctx->handle, &_content_block);
    PT_RETURN(res != OK, res, "read_block failed");

    // TODO define name hash size
    res = _content_block.traverse(get_handle(), (uint32_t)list_ctx->list_offset.name_hash, name_content_traverse_func, ctx);
    PT_RETURN(res != OK && res != EStoreRes::STOP, res, "content_block traverse failed");

    return OK;
}

static EStoreRes name_range_traverse_func(Layout::LAddress addr, uint16_t idx, void *ctx)
{
    ListElementsCtx *list_elements_ctx = (ListElementsCtx *)ctx;
    return list_elements_ctx->element->name_range_traverse(addr, idx, ctx);
}

EStoreRes ContainerElement::name_range_traverse(Layout::LAddress addr, uint16_t idx, void *ctx)
{
    DEBUG_ASSERT(addr.addr_type != Layout::AddrType::NONE);
    ListElementsCtx *list_ctx = (ListElementsCtx *)ctx;
    EStoreRes res = read_block(addr, list_ctx->handle, &_bitmap_block);
    PT_RETURN(res != OK, res, "read_block failed");

    list_ctx->res_offset.bitmap_idx = idx;
    res = _bitmap_block.traverse((uint32_t)list_ctx->list_offset.name_hash, name_bitmap_traverse_func, ctx);
    PT_RETURN(res != OK && res != EStoreRes::STOP, res, "bitmap_block traverse failed");
    // just used for the first bitmap
    list_ctx->list_offset.name_hash = 0;

    return OK;
}

EStoreRes ContainerElement::list_elements(uint64_t offset, uint64_t element_version, ListCallback list_cb,
                                          void *list_ctx, UNUSED const char *prefix, UNUSED char delimiter,
                                          uint64_t *current_element_version)
{
    EHandle handle = get_handle();
    if (element_version != 0 && get_attr()->ctime != element_version) {
        PTC_INFO("invalid element_version=%lu handle=0x%lx current_version=%lu",
                 element_version, handle, _handle_block.get_attr()->ctime);
        return EStoreRes::INVALID_ELEMENT_VERSION;
    }

    ListOffset list_offset = *(ListOffset *)&offset;
    ListElementsCtx ctx = {
        .element = this,
        .list_cb = list_cb,
        .caller_ctx = list_ctx,
        .list_offset = list_offset,
        .handle = handle,
    };
    // get ranges block
    LAddress range_addr = _handle_block.get_ranges_addr();
    EStoreRes res = read_block(range_addr, handle, &_range_block);
    PT_RETURN(res != OK, res, "failed to read block addr=0x%lx", range_addr.as_number());

    // TODO update dir atime?
    if (current_element_version) {
        *current_element_version = get_attr()->ctime;
    }

    if (range_addr.addr_type == LAddrType::NONE) {
        // if the ranges block does not exist
        PTC_INFO("handle=0x%lx does not have a range block", handle);
        return OK;
    }
    // TODO support multiple range blocks

    res = _range_block.traverse(list_offset.bitmap_idx, name_range_traverse_func, &ctx);
    PT_RETURN(res != OK && res != EStoreRes::STOP, res, "range_block traverse failed");

    return OK;
}

}
