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

    LOOP(P::N_SHARDS, i) {
        EAddress wbs_start_addr = { EAddrType::WRITE_BUFFER, i, 0 };
        uint64_t wb_size;
        _eio->get_addr_type_info(i, EAddrType::WRITE_BUFFER, &wb_size);

        EAddress shard_md_addr = { EAddrType::SHARD_MD, i, 0 };
        EStoreRes res = _eio->read_md(shard_md_addr, md_block.get_buffer(), false, nullptr);
        ASSERT(res == OK, "failed to load shard md");
        ASSERT(md_block.get_type() == BlockType::SHARD_MD_HEADER);
        _shard_md[i] = *md_block.get_md_header();

        ASSERT(md_block.get_md_header()->active_ingest_index < md_block.get_md_header()->n_write_buffers);
        EAddress wb_addr = wbs_start_addr;
        wb_addr.offset += md_block.get_md_header()->active_ingest_index * WRITE_BUFFER_SIZE;
        _ingest_buffers[i].init(_eio, wb_addr);
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

    LOOP(P::N_SHARDS, i) {
        EAddress wbs_start_addr = { EAddrType::WRITE_BUFFER, i, 0 };
        uint64_t wb_size;
        _eio->get_addr_type_info(i, EAddrType::WRITE_BUFFER, &wb_size);
        uint32_t n_write_buffers = wb_size / WRITE_BUFFER_SIZE;
        // reset all write buffers
        LOOP(n_write_buffers, j) {
            EAddress wb_addr = wbs_start_addr;
            wb_addr.offset += j * WRITE_BUFFER_SIZE;
            _ingest_buffers[i].init(_eio, wb_addr);
            EStoreRes res = _ingest_buffers[i].reset();
            ASSERT(res == OK);
        }
        // init the currently active write buffer
        EAddress wb_addr = wbs_start_addr;
        wb_addr.offset += md_block.get_md_header()->active_ingest_index * WRITE_BUFFER_SIZE;
        _ingest_buffers[i].init(_eio, wb_addr);
        
        // calc the number of physical hash table buckets
        uint64_t handle_table_size;
        _eio->get_addr_type_info(0, EAddrType::HANDLE_TABLE, &handle_table_size);
        ASSERT(handle_table_size % NVRAM_MD_BLOCK_SIZE == 0);
        ShardMdHeader *shard_md_header = md_block.get_md_header();
        shard_md_header->n_phys_buckets = handle_table_size / NVRAM_MD_BLOCK_SIZE;
        shard_md_header->n_write_buffers = n_write_buffers;

        EAddress shard_md_addr = { EAddrType::SHARD_MD, i, 0 };
        EStoreRes res = _eio->write_md(shard_md_addr, md_block.get_buffer());
        ASSERT(res == OK, "failed to write shard md");
        _shard_md[i] = *md_block.get_md_header();
    }
}

WriteBuffer *ShardMd::get_ingest_buffer(P::ShardId shard_id)
{
    return &_ingest_buffers[shard_id];
}

WriteBuffer *ShardMd::get_migrate_buffer(P::ShardId shard_id)
{
    return nullptr;
}

EStoreRes ShardMd::queue_for_migration(P::ShardId shard_id, WriteBuffer *write_buffer)
{
    // TODO lock, locking must make sure that if multiple ingests try to queue for migration only one will actually succeed
    BuffersGuard buffers_guard(_eio, 1);
    ShardMdBlock md_block;
    md_block.init(buffers_guard.get_next());

    EStoreRes state_update_res = write_buffer->move_to_migrate_state();
    // can fail due to a race, in which case we only need to update our write buffer address
    PT_RETURN(state_update_res != OK && state_update_res != EStoreRes::NOT_IN_INGEST, state_update_res,
              "move_to_migrate_state failed");

    EAddress shard_md_addr = { EAddrType::SHARD_MD, shard_id, 0 };
    EStoreRes res = _eio->read_md(shard_md_addr, md_block.get_buffer());
    PT_RETURN(res != OK, res, "read_md failed addr=0x%lx", shard_md_addr.as_number());

    ShardMdHeader *md_header = md_block.get_md_header();
    if (state_update_res == OK) {
        // won the race update the next write buffer in the shard md
        uint32_t next_ingest = md_header->active_ingest_index + 1 % md_header->n_write_buffers;
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
    }

    EAddress wb_addr = { EAddrType::WRITE_BUFFER, shard_id, 0 };
    wb_addr.offset += md_header->active_ingest_index * WRITE_BUFFER_SIZE;
    write_buffer->update_address(wb_addr);

    return OK;
}

EStoreRes ShardMd::free_buffer(P::ShardId shard_id, WriteBuffer *write_buffer)
{
    return OK;
}

}


