#include "plasma/io/devio.hpp"
#include "estore/io/estore_io.hpp"

namespace EStore {

static_assert(IO_ALIGNMENT == P::IO::DevIO::O_DIRECT_ALIGNMENT, "alignment defines must match");
using EStoreRes::OK;
using P::IO::IOVec;
using P::IO::IOVecs;
using MirroredIO::MIO;
using P::FiberSync::FutureRes;

void EStoreIO::init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id, MirroredIO::MIO *mio)
{
    _mio = mio;
    _md_pool.init(N_DATA_BUFFERS, NVRAM_MD_BLOCK_SIZE, IO_ALIGNMENT);
    _data_pool.init(N_DATA_BUFFERS, ALLOCATED_DATA_BUFFER_SIZE, IO_ALIGNMENT);

    _section_allocator.init(silo_id, module_id, rpc_fiber_group_id);
    _block_allocator.init(mio, &_section_allocator);
}

void EStoreIO::destroy()
{
    _md_pool.destroy();
    _data_pool.destroy();
}

EStoreRes EStoreIO::mio_to_estore_res(MIO::ReadRet res)
{
    switch (res) {
        case MIO::ReadRet::SUCCESS:
            return EStoreRes::OK;
        case MIO::ReadRet::REQUIRES_WRITE_LOCK:
            return EStoreRes::REQUIRES_WRITE_LOCK;
        case MIO::ReadRet::IO_ERROR:
            return EStoreRes::IO_ERROR;
        case MIO::ReadRet::DATA_CORRUPTION:
            return EStoreRes::DATA_CORRUPTION;
    }
}

EStoreRes EStoreIO::bool_to_estore_res(bool res)
{
    if (res == false)
        return EStoreRes::IO_ERROR;
    return EStoreRes::OK;
}

EStoreRes EStoreIO::read_md(LAddress addr, MIOBuffer *buff, bool locked, FutureRes<MIO::ReadRet> *future)
{
    Layout::MirroredAddress mir_addr = _section_allocator.translate(addr, buff->get_data_size());
    return mio_to_estore_res(_mio->protected_read(mir_addr, buff, locked, future));
}

EStoreRes EStoreIO::read_data(LAddress addr, IOVecs *iovecs, FutureRes<bool> *future)
{
    // TODO avoid doing iovecs->total_length()
    Layout::MirroredAddress mir_addr = _section_allocator.translate(addr, iovecs->total_length());
    return bool_to_estore_res(_mio->read(mir_addr, iovecs, future));
}

EStoreRes EStoreIO::write_md(LAddress addr, MIOBuffer *buff, FutureRes<bool> *future)
{
    Layout::MirroredAddress mir_addr = _section_allocator.translate(addr, buff->get_data_size());
    return bool_to_estore_res(_mio->protected_write(mir_addr, buff, future, nullptr));
}

EStoreRes EStoreIO::write_data(LAddress addr, IOVecs *iovecs, FutureRes<bool> *future)
{
    // TODO avoid doing iovecs->total_length()
    Layout::MirroredAddress mir_addr = _section_allocator.translate(addr, iovecs->total_length());
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
    LOOP(iovecs->count, i) {
        _data_pool.free_address(iovecs->iovecs[i].iov_base);
    }
}

EStoreRes EStoreIO::create_block_allocator(LAddrType type)
{
    LOOP(_section_allocator.get_addr_type_shard_count(type), i) {
        bool res = _block_allocator.create(i, type);
        if (res == false) {
            return EStoreRes::IO_ERROR;
        }
    }
    return EStoreRes::OK;
}

EStoreRes EStoreIO::alloc_md_block(P::ShardId shard_id, LAddrType type, LAddress *addr)
{
    return _block_allocator.alloc(shard_id, type, addr);
}

EStoreRes EStoreIO::free_md_block(LAddress addr)
{
    return bool_to_estore_res(_block_allocator.free(&addr));
}

uint64_t EStoreIO::get_total_addr_type_size(P::ShardId shard_id, LAddrType type)
{
    return _section_allocator.get_total_addr_type_size(shard_id, type);
}

}
