#include "estore/metadata/data_content_block.hpp"
#include "estore/metadata/name_content_block.hpp"
#include "estore/defs/estore_defs.hpp"
#include "estore/metadata/extents_aggregator.hpp"
#include "migrate.hpp"

namespace EStore {

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

using EStoreRes::OK;

void Migrate::init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table)
{
    _eio = eio;
    _shard_md = shard_md;
    _handles_table = handles_table;
}

EStoreRes Migrate::migrate(P::ShardId shard_id)
{
    BuffersGuard buffers_guard(_eio, 5);
    LAddress addr;

    EStoreRes res = _shard_md->get_migrate_buffer_addr(&buffers_guard, shard_id, &addr);
    if (res == EStoreRes::NOENT) {
        PTC_DEBUG("no write buffer to migrate for shard_id=%u", shard_id);
        return OK;
    } else if (res != OK) {
        PTC_ERROR("get_migrate_buffer_addr failed");
        return res;
    }

    MigrateBuffer migrate_buffer;
    migrate_buffer.init(_eio, _shard_md, shard_id, addr);

    res = migrate_buffer.begin_migrate(&buffers_guard);
    PT_RETURN(res != OK, res, "begin_migrate failed");

    ExtentsAggregator extents_aggregator;
    extents_aggregator.init(UINT64_MAX, UINT32_MAX);
    // read MD blocks in a loop, aggregate as much operations as possible (TODO in the future till the next snapline)
    MIOBuffer *block_buffer = buffers_guard.get_next();
    res = migrate_buffer.get_next_md_block(block_buffer);
    while (res == OK) {
        BaseBlock base_block;
        base_block.set_buffer(block_buffer);
        switch (base_block.get_type()) {
            case BlockType::NAME_CONTENT_BLOCK:
                res = migrate_names(block_buffer);
                break;
            case BlockType::DATA_CONTENT_BLOCK:
                res = migrate_data(&extents_aggregator, block_buffer);
                break;
            case BlockType::NAME_BITMAP_BLOCK:
                PTC_DEBUG("skipping NAME_BITMAP_BLOCK during migrate");
                break;
            case BlockType::DATA_BITMAP_BLOCK:
                PTC_DEBUG("skipping DATA_BITMAP_BLOCK during migrate");
                break;
            case BlockType::NAME_RANGE_BLOCK:
            case BlockType::DATA_RANGE_BLOCK:
            case BlockType::HANDLE_BLOCK:
            case BlockType::INVALID_BLOCK_TYPE:
            case BlockType::COMPOSITE_BLOCK:
            case BlockType::WRITE_BUFFER_HEADER:
            case BlockType::SHARD_MD_HEADER:
                PANIC("unexpected block type in write buffer " << (uint64_t)base_block.get_type());
        }
        PT_RETURN(res != OK, res, "migration failed");

        res = migrate_buffer.get_next_md_block(block_buffer);
    }

    // Note: migrate should strive to keep running as much as possible in order to fill stripes.
    // TODO in case migrate cannot proceed for some reason and we are unable to fill a sub stripe we might be required
    // to flush a sub stripe without fully writing it

    return OK;
}

EStoreRes Migrate::migrate_names(MIOBuffer *block_buffer)
{
    NameContentBlock content_block;
    content_block.set_buffer(block_buffer);

    // add data in content block to migrate tree

    return OK;
}

EStoreRes Migrate::migrate_data(ExtentsAggregator *extents_aggregator, MIOBuffer *block_buffer)
{
    DataContentBlock content_block;
    content_block.set_buffer(block_buffer);

    // add data in content block to migrate tree
    EStoreRes res = content_block.export_all(extents_aggregator);
    PT_RETURN(res != OK, res, "content_block.export_all failed");

    return OK;
}

}


