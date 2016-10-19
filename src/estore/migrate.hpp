/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/metadata/shard_md.hpp"
#include "estore/metadata/handles_table.hpp"

namespace EStore {

class Migrate {
public:
    void init(EStoreIO *eio, ShardMd *shard_md, HandlesTable *handles_table);

    EStoreRes migrate(P::ShardId shard_id);


private:
    EStoreRes migrate_names(MIOBuffer *block_buffer);
    EStoreRes migrate_data(ExtentsAggregator *extents_aggregator, MIOBuffer *block_buffer);

private:
    EStoreIO *_eio;
    ShardMd *_shard_md;
    HandlesTable *_handles_table;
};

}

