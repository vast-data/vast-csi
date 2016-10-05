#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "phys/mirrored_io/mio.hpp"
#include "phys/layout/section_allocator.hpp"
#include "phys/layout/block_allocator.hpp"
#include "plasma/utils/io.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/fiber/sync/future.hpp"
#include "estore/defs/estore_defs.hpp"

namespace EStore {

#define IO_ALIGN_UP(LEN)    POW2_ROUND_UP(LEN, IO_ALIGNMENT)
#define IO_ALIGN_DOWN(LEN)  POW2_ROUND_DOWN(LEN, IO_ALIGNMENT)

typedef MirroredIO::MIO::Buffer MIOBuffer;

class EStoreIO {
public:
    void init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id, MirroredIO::MIO *mio);
    void destroy();

    // All IO operations must be aligned to P::DevIO::O_DIRECT_ALIGNMENT size

    // read metadata (protected) from the given address, buffer must be pre allocated
    EStoreRes WARN_UNUSED read_md(LAddress addr, MIOBuffer *buff, bool locked = false,
                                  P::FiberSync::FutureRes<MirroredIO::MIO::ReadRet> *future = nullptr);
    // read data (unprotected) from the given address, buffer must be pre allocated
    EStoreRes WARN_UNUSED read_data(LAddress addr, P::IO::IOVecs *iovecs, P::FiberSync::FutureRes<bool> *future);

    // write metadata (protected) from the given address, buffer must be pre allocated
    EStoreRes WARN_UNUSED write_md(LAddress addr, MIOBuffer *buff, P::FiberSync::FutureRes<bool> *future = nullptr);
    // write data (unprotected) to the given address, buffer must be pre allocated
    EStoreRes WARN_UNUSED write_data(LAddress addr, P::IO::IOVecs *iovecs, P::FiberSync::FutureRes<bool> *future = nullptr);

    // blocking allocation of multiple MIO buffers
    void alloc_md_buffers(uint16_t n_buffers, MIOBuffer *buffers OUT);
    // free multiple MIO buffers
    void free_md_buffers(uint16_t n_buffers, MIOBuffer *buffers);
    // blocking allocation of multiple data buffers (will allocate iovecs->count buffers)
    void alloc_data_buffers(P::IO::IOVecs *iovecs INOUT);
    // free data buffers
    void free_data_buffers(P::IO::IOVecs *iovecs);

    EStoreRes create_block_allocator(LAddrType type);
    // returns to address to a NVRAM_MD_BLOCK_SIZE sized block, out of which only NVRAM_USABLE_BLOCK_SIZE may be used
    EStoreRes WARN_UNUSED alloc_md_block(P::ShardId shard_id, LAddrType type, LAddress *addr OUT);
    // free a previously allocated md block
    EStoreRes free_md_block(LAddress addr IN);

    // returns the size of the write buffers for the specified shard
    uint64_t get_total_addr_type_size(P::ShardId shard_id, LAddrType type);

private:
    EStoreRes mio_to_estore_res(MirroredIO::MIO::ReadRet res);
    EStoreRes bool_to_estore_res(bool res);

    MirroredIO::MIO *_mio;
    Layout::SectionAllocator _section_allocator;
    Layout::BlockAllocator _block_allocator;
    P::Pool _md_pool;
    P::Pool _data_pool;
};

}
