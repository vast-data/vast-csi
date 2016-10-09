/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/io/estore_io.hpp"
#include "shard_md.hpp"

namespace EStore {

class HandlesTable {
public:
    void init(EStoreIO *eio, ShardMd *shard_md);
    void destroy();

    EStoreRes create();
    void load();
    EStoreRes resize(uint32_t n_buckets);

    // read / write bucket sized buffers
    EStoreRes WARN_UNUSED write(EHandle handle, MIOBuffer *bucket_data);
    EStoreRes WARN_UNUSED read(EHandle handle, MIOBuffer *bucket_data);
    EStoreRes WARN_UNUSED read_by_virt_bucket(VirtualBucketId virt_bucket, MIOBuffer *bucket_data);

    // [16 bit handle index, 48 bit virtual bucket id]
    static const uint64_t HANDLE_INDEX_MASK = 0xffff000000000000;
    static const uint64_t BUCKET_MASK       = 0x0000ffffffffffff;
    static VirtualBucketId handle_to_virt_bucket(EHandle handle) { return handle & BUCKET_MASK; }
    static uint64_t handle_to_handle_index(EHandle handle) { return handle >> 48; }
    static EHandle build_handle(uint64_t handle_index, VirtualBucketId virt_bucket)
    {
        EHandle handle = handle_index << 48;
        handle = handle | (virt_bucket & BUCKET_MASK);
        return handle;
    }
    P::ShardId handle_to_shard_id(EHandle handle) { return handle_to_virt_bucket(handle) % _eio->get_shard_count(); }

private:
    LAddress handle_to_addr(EHandle handle);
    LAddress virt_bucket_to_addr(VirtualBucketId virt_bucket);
    LAddress phys_bucket_to_addr(uint64_t phys_bucket, P::ShardId shard_id);

private:

    EStoreIO *_eio;
    ShardMd *_shard_md;
    uint32_t _total_phys_buckets;
};

}
