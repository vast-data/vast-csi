#include "estore/io/buffers_guard.hpp"
#include "plasma/trace/emitter.hpp"
#include "handles_table.hpp"
#include "composite_block.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE

namespace EStore {

using EStoreRes::OK;


void HandlesTable::init(EStoreIO *eio, ShardMd *shard_md)
{
    _eio = eio;
    _shard_md = shard_md;
    _total_phys_buckets = 0;
}

void HandlesTable::destroy()
{

}

EStoreRes HandlesTable::create()
{
    BuffersGuard buffers_guard(_eio, 1);
    // init the hash table with empty composite blocks
    MIOBuffer *bucket_buffer = buffers_guard.get_next();
    memset(bucket_buffer->get_data(), 0, bucket_buffer->get_data_size());
    CompositeBlock composite_block;
    composite_block.init(bucket_buffer);

    uint32_t buckets_per_shard = _shard_md->get_shard_n_phys_buckets(0);
    LOOP(P::N_SHARDS, shard_id) {
        uint32_t shard_phys_buckets = _shard_md->get_shard_n_phys_buckets(shard_id);
        // TODO support a different number of buckets per shard? as long as we don't verify so there will be no surprises
        ASSERT_EQUAL(buckets_per_shard, shard_phys_buckets);
        _total_phys_buckets += shard_phys_buckets;
        LOOP(shard_phys_buckets, i) {
            EAddress addr = phys_bucket_to_addr(i, shard_id);
            EStoreRes res = _eio->write_md(addr, composite_block.get_buffer());
            PT_RETURN(res != OK, res, "write to addr=0x%lx failed", *(uint64_t *)&addr);
        }
    }

    return OK;
}

void HandlesTable::load()
{
    LOOP(P::N_SHARDS, shard_id) {
        uint32_t shard_phys_buckets = _shard_md->get_shard_n_phys_buckets(shard_id);
        _total_phys_buckets += shard_phys_buckets;
    }
}

EStoreRes HandlesTable::resize(uint32_t n_buckets)
{
    PANIC("not implemented");
    return OK;
}

EStoreRes HandlesTable::write(EHandle handle, MIOBuffer *bucket_data)
{
    EAddress addr = handle_to_addr(handle);
    PT_DEBUG(DATA, "write to addr=0x%lx", addr.as_number());
    EStoreRes res = _eio->write_md(addr, bucket_data);
    PT_RETURN(res != OK, res, "write to addr=0x%lx failed", addr.as_number());

    return OK;
}

EStoreRes HandlesTable::read(EHandle handle, MIOBuffer *bucket_data)
{
    uint64_t virt_bucket = handle_to_virt_bucket(handle);
    return read_by_virt_bucket(virt_bucket, bucket_data);
}

EStoreRes HandlesTable::read_by_virt_bucket(VirtualBucketId virt_bucket, MIOBuffer *bucket_data)
{

    EAddress addr = virt_bucket_to_addr(virt_bucket);
    PT_DEBUG(DATA, "read from addr=0x%lx", addr.as_number());
    EStoreRes res = _eio->read_md(addr, bucket_data, false, nullptr);
    PT_RETURN(res != OK, res, "read from addr=0x%lx failed", addr.as_number());
    return OK;
}

EAddress HandlesTable::virt_bucket_to_addr(VirtualBucketId virt_bucket)
{
    // TODO consistent hash
    P::ShardId shard_id = virt_bucket % P::N_SHARDS;
    uint64_t phys_bucket_idx = virt_bucket / _total_phys_buckets;
    uint64_t phys_bucket_per_shard = _total_phys_buckets / P::N_SHARDS;
    uint64_t phys_bucket = phys_bucket_idx % phys_bucket_per_shard;
    return phys_bucket_to_addr(phys_bucket, shard_id);
}

EAddress HandlesTable::phys_bucket_to_addr(uint64_t phys_bucket, P::ShardId shard_id)
{
    EAddress addr {
        .addr_type = EAddrType::HANDLE_TABLE,
        .shard_id = shard_id,
        .offset = phys_bucket * NVRAM_MD_BLOCK_SIZE,
    };
    return addr;
}

EAddress HandlesTable::handle_to_addr(EStore::EHandle handle)
{
    VirtualBucketId virt_id = handle_to_virt_bucket(handle);
    return virt_bucket_to_addr(virt_id);
}

}