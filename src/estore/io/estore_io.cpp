#include "plasma/io/devio.hpp"
#include "estore/io/estore_io.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE;

namespace EStore {

static_assert(IO_ALIGNMENT == P::IO::DevIO::O_DIRECT_ALIGNMENT, "alignment defines must match");
using EStoreRes::OK;
using P::IO::IOVec;
using P::IO::IOVecs;
using MirroredIO::MIO;
using P::FiberSync::FutureRes;

void EStoreIO::init()
{
    _md_pool.init(N_DATA_BUFFERS, NVRAM_MD_BLOCK_SIZE, IO_ALIGNMENT);
    _data_pool.init(N_DATA_BUFFERS, ALLOCATED_DATA_BUFFER_SIZE, IO_ALIGNMENT);
}

void EStoreIO::destroy()
{
    _md_pool.destroy();
    _data_pool.destroy();
}

EStoreRes EStoreIO::mio_to_estore_res(MIO::ReadRet res)
{
    switch (res) {
        case MIO::ReadRet::Success:
            return EStoreRes::OK;
        case MIO::ReadRet::RequiresWriteLock:
        case MIO::ReadRet::IOError:
        case MIO::ReadRet::DataCorruption:
            PANIC();
    }
}

EStoreRes EStoreIO::bool_to_estore_res(bool res)
{
    if (!res)
        PANIC();
    return EStoreRes::OK;
}

EStoreRes WARN_UNUSED EStoreIO::read_md(EAddress addr, MIOBuffer *buff, bool locked, FutureRes<MIO::ReadRet> *future)
{
    P::IO::MirroredAddressToken mir_addr = _shard_layout->translate(addr, buff->get_data_size());
    return mio_to_estore_res(_mio->protected_read(mir_addr, buff, locked, future));
}

EStoreRes WARN_UNUSED EStoreIO::read_data(EAddress addr, IOVecs *iovecs, FutureRes<bool> *future)
{
    P::IO::MirroredAddressToken mir_addr = _shard_layout->translate(addr, iovecs->total_length());
    return bool_to_estore_res(_mio->read(mir_addr, iovecs, future));
}

EStoreRes EStoreIO::write_md(EAddress addr, MIOBuffer *buff, FutureRes<bool> *future)
{
    P::IO::MirroredAddressToken mir_addr = _shard_layout->translate(addr, buff->get_data_size());
    return bool_to_estore_res(_mio->protected_write(mir_addr, buff, future, nullptr));
}

EStoreRes EStoreIO::write_data(EAddress addr, IOVecs *iovecs, FutureRes<bool> *future)
{
    P::IO::MirroredAddressToken mir_addr = _shard_layout->translate(addr, iovecs->total_length());
    return bool_to_estore_res(_mio->write(mir_addr, iovecs, future));
}

void EStoreIO::alloc_md_buffers(uint16_t n_buffers, MIOBuffer *buffers)
{
    DEBUG_ASSERT(n_buffers > 0);
    LOOP(n_buffers, i) {
        buffers[i].init((P::byte *)_md_pool.alloc_address(), NVRAM_MD_BLOCK_SIZE);
    }
}

void EStoreIO::free_md_buffers(uint16_t n_buffers, MirroredIO::MIO::Buffer *buffers)
{
    DEBUG_ASSERT(n_buffers > 0);
    LOOP(n_buffers, i) {
        _md_pool.free_address(buffers[i].get_mio_vec()->iov_base);
    }
}

void EStoreIO::alloc_data_buffers(IOVecs *iovecs)
{
    DEBUG_ASSERT(iovecs->count > 0);
    LOOP(iovecs->count, i) {
        iovecs->iovecs[i].iov_base = _data_pool.alloc_address();
        iovecs->iovecs[i].iov_len = NVRAM_MD_BLOCK_SIZE;
    }
}

void EStoreIO::free_data_buffers(IOVecs *iovecs)
{
    DEBUG_ASSERT(iovecs->count > 0);
    LOOP(iovecs->count, i) {
        _data_pool.free_address(iovecs->iovecs[i].iov_base);
    }
}

EAddress EStoreIO::alloc_md_block(P::ShardId shard_id, EAddrType type, VirtualBucketId virt_bucket)
{
    return EAddress();
}

void EStoreIO::free_md_block(EAddress addr)
{

}

void EStoreIO::get_addr_type_info(P::ShardId shard_id, EAddrType type, uint64_t *size_bytes)
{
    _shard_layout->get_addr_type_info(shard_id, type, size_bytes);
}

}

