/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/io/estore_io.hpp"
#include "estore/defs/estore_defs.hpp"
#include "write_buffer.hpp"

namespace EStore {

struct ShardMdHeader {
    uint32_t n_write_buffers;
    uint32_t active_ingest_index;
    uint32_t active_migrate_index;
    uint32_t n_phys_buckets;
};

class ShardMdBlock : public BaseBlock {
public:
    virtual void init(MIOBuffer *buffer);
    void reset();

    ShardMdHeader *get_md_header() { return (ShardMdHeader *)payload_start(); }
};


// manages shards metadata
class ShardMd {
public:
    void init(EStoreIO *eio);
    void destroy();

    void create();
    void load();

    // returns a pointer to the current ingest write buffer
    WriteBuffer *get_ingest_buffer(P::ShardId shard_id);
    // returns a pointer to the oldest buffer that is ready for migration
    WriteBuffer *get_migrate_buffer(P::ShardId shard_id);
    // queue an ingest buffer for migration
    EStoreRes WARN_UNUSED free_buffer(P::ShardId shard_id, WriteBuffer *write_buffer);

    // update shard md to point to the next ingest buffer
    EStoreRes WARN_UNUSED switch_ingest_buffer(BuffersGuard *buffers_guard, P::ShardId shard_id, LAddress *wb_addr);
    // return the address of the current ingest buffer
    EStoreRes WARN_UNUSED get_ingest_addr(BuffersGuard *buffers_guard, P::ShardId shard_id, LAddress *wb_addr);


    uint32_t get_shard_n_phys_buckets(P::ShardId shard_id) { return _shard_md[shard_id].n_phys_buckets; }

private:
    LAddress calc_ingest_addr(ShardMdHeader *header, P::ShardId shard_id);

private:
    EStoreIO *_eio;
    ShardMdHeader _shard_md[P::MAX_SHARDS];
    WriteBuffer _ingest_buffers[P::MAX_SHARDS];
};

}
