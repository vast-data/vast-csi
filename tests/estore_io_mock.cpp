#include <map>
#include <fstream>
#include <fcntl.h>
#include <sys/uio.h>
#include <unistd.h>
#include "plasma/utils/assert.hpp"
#include "plasma/utils/os.hpp"
#include "estore/io/estore_io.hpp"
#include "estore/metadata/write_buffer.hpp"

#define CURRENT_COMPONENT ComponentId::TEST
#define CURRENT_CHANNEL DATA

namespace EStore {

#define N_WRITE_BUFFERS 4
std::map<std::string, int> fd_map;
uint64_t current_addr = 2 + N_WRITE_BUFFERS;

using EStoreRes::OK;
using P::IO::IOVec;
using P::IO::IOVecs;
using P::FiberSync::FutureRes;
using MirroredIO::MIO;

void EStoreIO::init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id, MirroredIO::MIO *mio)
{
    current_addr = 2 + N_WRITE_BUFFERS;
    P::ensure_directory_exists("/tmp/eio_mock_data");
}

void EStoreIO::destroy()
{
    for (auto fd_iter : fd_map) {
        close(fd_iter.second);
    }
    fd_map.clear();
}

static int get_mock_fd(LAddress addr)
{
    if (fd_map.size() > 500) {
        for (auto fd_iter : fd_map) {
            close(fd_iter.second);
        }
        fd_map.clear();
    }
    char filename[64];
    sprintf(filename, "/tmp/eio_mock_data/eio_mock_file_%lu_%lu", addr.addr_type, addr.shard_id);
    auto iter = fd_map.find(filename);
    int fd;
    if (iter == fd_map.end()) {
        fd = open(filename, O_RDWR | O_CREAT /*| O_DIRECT*/, 0777);
        ASSERT_ERRNO(fd > 0);
        fd_map[filename] = fd;
        PTC_DEBUG("opened fd=%d for file=%s", fd, filename);
    } else {
        fd = iter->second;
    }
    ASSERT_ERRNO(fd > 0);
    return fd;
}

EStoreRes WARN_UNUSED EStoreIO::read_md(LAddress addr, MIOBuffer *buff, bool locked, FutureRes<MIO::ReadRet> *future)
{
    int fd = get_mock_fd(addr);
    PT_DEBUG(DATA, "read addr=0x%lx offset=%lu fd=%d", addr.as_number(), addr.offset, fd);
    ASSERT(buff->get_raw_size() == NVRAM_MD_BLOCK_SIZE);
    ASSERT((size_t)buff->get_mio_vec()->iov_base % IO_ALIGNMENT == 0);
    ssize_t res = pread(fd, buff->get_mio_vec()->iov_base, buff->get_raw_size(), addr.offset);
    if (res != buff->get_raw_size()) {
        PTC_ERROR("requested %lu bytes got res=%ld bytes errno=%d", buff->get_raw_size(), res, errno);
    }
    ASSERT_ERRNO(res == buff->get_raw_size());
    if (future) {
        future->set();
    }
    return OK;
}

EStoreRes EStoreIO::write_md(LAddress addr, MIOBuffer *buff, FutureRes<bool> *future)
{
//    PT_DEBUG(DATA, "write addr=0x%lx", addr.as_number());
    int fd = get_mock_fd(addr);
    ASSERT_OP(buff->get_raw_size(), ==, NVRAM_MD_BLOCK_SIZE);
    ASSERT_OP((size_t)buff->get_mio_vec()->iov_base % IO_ALIGNMENT, ==, 0);
    memset(buff->get_mio_vec()->iov_base, 0xff, MIO_OVERHEAD);
    ssize_t res = pwrite(fd, buff->get_mio_vec()->iov_base, buff->get_raw_size(), addr.offset);
    ASSERT_ERRNO(res == buff->get_raw_size());
    if (future) {
        future->set();
    }
    return OK;
}

EStoreRes WARN_UNUSED EStoreIO::read_data(LAddress addr, IOVecs *iovecs, FutureRes<bool> *future)
{
    int fd = get_mock_fd(addr);
    LOOP(iovecs->count, i) {
//        PT_DEBUG(DATA, "iov_len=%lu iov_base=%lu", iovecs->iovecs[i].iov_len, (size_t)iovecs->iovecs[i].iov_base);
        ASSERT(iovecs->iovecs[i].iov_len % IO_ALIGNMENT == 0);
        ASSERT((size_t)iovecs->iovecs[i].iov_base % IO_ALIGNMENT == 0);
    }
    ASSERT(addr.offset % IO_ALIGNMENT == 0);
    PT_DEBUG(DATA, "read from fd=%d offset=%lu len=%lu", fd, addr.offset, iovecs->total_length());
    ssize_t res = preadv(fd, iovecs->iovecs, iovecs->count, addr.offset);;
    ASSERT_ERRNO(res > 0);
    if (future) {
        future->set();
    }
    return OK;
}

EStoreRes EStoreIO::write_data(LAddress addr, P::IO::IOVecs *iovecs, FutureRes<bool> *future)
{
    int fd = get_mock_fd(addr);
    LOOP(iovecs->count, i) {
//        PT_DEBUG(DATA, "vec(%lu) iov_len=%lu iov_base=%p", i, iovecs->iovecs[i].iov_len, iovecs->iovecs[i].iov_base);
        ASSERT(iovecs->iovecs[i].iov_len % IO_ALIGNMENT == 0);
        ASSERT((size_t)iovecs->iovecs[i].iov_base % IO_ALIGNMENT == 0);
    }
    PT_DEBUG(DATA, "write to fd=%d offset=%lu len=%lu", fd, addr.offset, iovecs->total_length());
    ASSERT(addr.offset % IO_ALIGNMENT == 0);
    ssize_t res = pwritev(fd, iovecs->iovecs, iovecs->count, addr.offset);
    ASSERT_ERRNO(res > 0);

    if (future) {
        future->set();
    }
    return OK;
}

void EStoreIO::alloc_md_buffers(uint16_t n_buffers, MIOBuffer *buffers)
{
    ASSERT(n_buffers > 0);
//    PT_DEBUG(DATA, "alloc %hu buffers", n_buffers);
    LOOP(n_buffers, i) {
        buffers[i].init((P::byte *)aligned_alloc(IO_ALIGNMENT, NVRAM_MD_BLOCK_SIZE), NVRAM_MD_BLOCK_SIZE);
    }
}

void EStoreIO::free_md_buffers(uint16_t n_buffers, MIOBuffer *buffers)
{
    ASSERT(n_buffers > 0);
    LOOP(n_buffers, i) {
        memset(buffers[i].get_mio_vec()->iov_base, 0xff, buffers[i].get_mio_vec()->iov_len);
        free(buffers[i].get_mio_vec()->iov_base);
        buffers[i].get_mio_vec()->iov_base = nullptr;
    }
//    PT_DEBUG(DATA, "free %hu buffers", n_buffers);
}


void EStoreIO::alloc_data_buffers(IOVecs *iovecs)
{
    ASSERT(iovecs->count > 0);
    PT_DEBUG(DATA, "alloc %u buffers", iovecs->count);
    LOOP(iovecs->count, i) {
        iovecs->iovecs[i].iov_base = (char *)aligned_alloc(IO_ALIGNMENT, ALLOCATED_DATA_BUFFER_SIZE);
        memset(iovecs->iovecs[i].iov_base, 0, ALLOCATED_DATA_BUFFER_SIZE);
        iovecs->iovecs[i].iov_len = DATA_BUFFER_SIZE;
    }
}

void EStoreIO::free_data_buffers(IOVecs *iovecs)
{
    ASSERT(iovecs->count > 0);
    PT_DEBUG(DATA, "free %u buffers", iovecs->count);
    LOOP(iovecs->count, i) {
        if (iovecs->iovecs[i].iov_base) {
            free(iovecs->iovecs[i].iov_base);
        }
    }
    iovecs->count = 0;
}

EStoreRes EStoreIO::create_block_allocator(LAddrType type)
{
    return EStoreRes::OK;
}

EStoreRes EStoreIO::alloc_md_block(P::ShardId shard_id, LAddrType type, LAddress *addr)
{
    addr->shard_id = shard_id;
    addr->addr_type = type;
    addr->offset = current_addr;
    current_addr += 1;
    return EStoreRes::OK;
}

EStoreRes EStoreIO::free_md_block(LAddress addr)
{
    return EStoreRes::OK;
}

uint64_t EStoreIO::get_total_addr_type_size(P::ShardId shard_id, LAddrType type)
{
    if (type == LAddrType::WRITE_BUFFER) {
        return WRITE_BUFFER_SIZE * N_WRITE_BUFFERS;
    } else {
        return NVRAM_MD_BLOCK_SIZE * 256;
    }
}

EStoreRes WARN_UNUSED EStoreIO::lock(LAddress addr, BlockType type, LockObject *lock_obj) {
    PANIC("");
}

EStoreRes WARN_UNUSED EStoreIO::unlock(LAddress addr, BlockType type, LockObject *lock_obj) {
    PANIC("");
}

}
