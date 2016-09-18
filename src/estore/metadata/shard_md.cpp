#include <estore/defs/estore_defs.hpp>
#include "estore/io/buffers_guard.hpp"
#include "shard_md.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

using EStoreRes::OK;

void ShardMdBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::SHARD_MD_HEADER);
    set_version(INITIAL_BLOCK_VER);
    ASSERT(space_left() >= sizeof(ShardMdHeader));
    add_used_bytes(sizeof(ShardMdHeader));
}

void ShardMdBlock::reset()
{
    ShardMdHeader *md_header = get_md_header();
    md_header->active_migrate_index = UINT32_MAX;
    md_header->active_ingest_index = 0;
}

void ShardMd::init(EStoreIO *eio)
{
    _eio = eio;
}

void ShardMd::destroy()
{

}

void ShardMd::load()
{
    BuffersGuard buffers_guard(_eio, 1);
    ShardMdBlock md_block;
    md_block.init(buffers_guard.get_next());

    LOOP(_eio->get_shard_count(), i) {
        LAddress wbs_start_addr = {LAddrType::WRITE_BUFFER, i, 0};

        LAddress shard_md_addr = {LAddrType::SHARD_MD, i, 0};
        EStoreRes res = _eio->read_md(shard_md_addr, md_block.get_buffer(), false, nullptr);
        ASSERT(res == OK, "failed to load shard md");
        ASSERT(md_block.get_type() == BlockType::SHARD_MD_HEADER);
        _shard_md[i] = *md_block.get_md_header();

        ASSERT(md_block.get_md_header()->active_ingest_index < md_block.get_md_header()->n_write_buffers);
        LAddress wb_addr = wbs_start_addr;
        wb_addr.offset += md_block.get_md_header()->active_ingest_index * WRITE_BUFFER_SIZE;
        _ingest_buffers[i].init(_eio, this, i, wb_addr);
    }
}

void ShardMd::create()
{
    // TODO make sure that we are not overwriting an existing system
    PT_INFO(DATA, "resetting shard MD");
    BuffersGuard buffers_guard(_eio, 1);
    ShardMdBlock md_block;
    md_block.init(buffers_guard.get_next());
    md_block.reset();

    LOOP(_eio->get_shard_count(), i) {
        LAddress wbs_start_addr = {LAddrType::WRITE_BUFFER, i, 0};
        uint32_t n_write_buffers = _eio->get_total_addr_type_size(i, LAddrType::WRITE_BUFFER) / WRITE_BUFFER_SIZE;
        // reset all write buffers
        LOOP(n_write_buffers, j) {
            LAddress wb_addr = wbs_start_addr;
            wb_addr.offset += j * WRITE_BUFFER_SIZE;
            _ingest_buffers[i].init(_eio, this, i, wb_addr);
            EStoreRes res = _ingest_buffers[i].reset();
            ASSERT(res == OK);
        }
        // init the currently active write buffer
        LAddress wb_addr = wbs_start_addr;
        wb_addr.offset += md_block.get_md_header()->active_ingest_index * WRITE_BUFFER_SIZE;
        _ingest_buffers[i].init(_eio, this, i, wb_addr);

        // calc the number of physical hash table buckets
        uint64_t handle_table_size = _eio->get_total_addr_type_size(i, LAddrType::HANDLE_TABLE);
        ASSERT(handle_table_size % NVRAM_MD_BLOCK_SIZE == 0);
        ShardMdHeader *shard_md_header = md_block.get_md_header();
        shard_md_header->n_phys_buckets = handle_table_size / NVRAM_MD_BLOCK_SIZE;
        shard_md_header->n_write_buffers = n_write_buffers;

        LAddress shard_md_addr = {LAddrType::SHARD_MD, i, 0};
        EStoreRes res = _eio->write_md(shard_md_addr, md_block.get_buffer());
        ASSERT(res == OK, "failed to write shard md");
        _shard_md[i] = *md_block.get_md_header();
    }
}

WriteBuffer *ShardMd::get_ingest_buffer(P::ShardId shard_id)
{
    return &_ingest_buffers[shard_id];
}

WriteBuffer *ShardMd::get_migrate_buffer(UNUSED P::ShardId shard_id)
{
    PANIC("not implemented");
    return nullptr;
}

LAddress ShardMd::calc_ingest_addr(ShardMdHeader *header, P::ShardId shard_id)
{
    LAddress wb_addr = {LAddrType::WRITE_BUFFER, shard_id, header->active_ingest_index * WRITE_BUFFER_SIZE};
    return wb_addr;
}

EStoreRes ShardMd::get_ingest_addr(BuffersGuard *buffers_guard, P::ShardId shard_id, LAddress *wb_addr)
{
    ShardMdBlock md_block;
    md_block.init(buffers_guard->get_next());
    LAddress shard_md_addr = {LAddrType::SHARD_MD, shard_id, 0};
    EStoreRes res = _eio->read_md(shard_md_addr, md_block.get_buffer());
    PT_RETURN(res != OK, res, "read_md failed addr=0x%lx", shard_md_addr.as_number());

    *wb_addr = calc_ingest_addr(md_block.get_md_header(), shard_id);
    return OK;
}

EStoreRes ShardMd::switch_ingest_buffer(BuffersGuard *buffers_guard, P::ShardId shard_id, LAddress *wb_addr)
{
    // TODO lock
    ShardMdBlock md_block;
    md_block.init(buffers_guard->get_next());
    LAddress shard_md_addr = {LAddrType::SHARD_MD, shard_id, 0};
    EStoreRes res = _eio->read_md(shard_md_addr, md_block.get_buffer());
    PT_RETURN(res != OK, res, "read_md failed addr=0x%lx", shard_md_addr.as_number());

    ShardMdHeader *md_header = md_block.get_md_header();
    uint32_t next_ingest = (md_header->active_ingest_index + 1) % md_header->n_write_buffers;
    PTC_DEBUG("switching write buffer active_ingest_index=%u active_migrate_index=%u next_ingest=%u",
              md_header->active_ingest_index, md_header->active_migrate_index, next_ingest);
    if (next_ingest == md_header->active_migrate_index) {
        // TODO need to wait for migrator
        PANIC("not implemented - out of write buffers");
    }
    if (md_header->active_migrate_index == UINT32_MAX) {
        md_header->active_migrate_index = md_header->active_ingest_index;
    }
    md_header->active_ingest_index = next_ingest;

    res = _eio->write_md(shard_md_addr, md_block.get_buffer());
    PT_RETURN(res != OK, res, "read_md failed addr=0x%lx", shard_md_addr.as_number());

    *wb_addr = calc_ingest_addr(md_block.get_md_header(), shard_id);
    return OK;
}

EStoreRes ShardMd::free_buffer(UNUSED P::ShardId shard_id, UNUSED WriteBuffer *write_buffer)
{
    PANIC("not implemented");
    return OK;
}

}
