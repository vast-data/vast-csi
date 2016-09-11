#include "mio.hpp"

#include "plasma/utils/math.hpp"
#include "plasma/io/base_io.hpp"
#include "plasma/io/devio.hpp"
#include "plasma/io/memio.hpp"

#include <zlib.h>

#define CURRENT_COMPONENT ComponentId::IO_MIRRORING

static const RetryParams read_retry_params = { .max_spinning_attempts = 2, .attempts_per_yield = 1, .max_attempts = 20 };
static const RetryParams write_retry_params = { .max_spinning_attempts = 2, .attempts_per_yield = 1, .max_attempts = 20 };
static const useconds_t wait_interval = 10;

using namespace P::IO;

namespace MirroredIO {

void MIO::init(P::SiloId silo_id, ModuleId module_id, P::Index fiber_group_id, Control::DevAgent *dev_agent,
               size_t concurrent_readers, size_t concurrent_writers, size_t concurrent_devices_asyncly_written)
{
    _readers.init(concurrent_readers);
    _writers.init(concurrent_writers);
    _future_pool.init(concurrent_devices_asyncly_written);
    _dev_agent = dev_agent;
    _mio_agent.init(silo_id, module_id, fiber_group_id, _dev_agent);
    _fiber_group_id = fiber_group_id;
}

void MIO::destroy()
{
    _readers.destroy();
    _writers.destroy();
    _future_pool.destroy();
    _mio_agent.destroy();
}


/// Mirrored IO ///

// TODO: consider using better CRC
uint16_t MIO::calc_buff_crc(Buffer *mio_buff)
{
    uint16_t initial_crc = crc32(0L, Z_NULL, 0);
    return crc32(initial_crc, mio_buff->get_data(), mio_buff->get_data_size());
}

//uint16_t MirroredIO::calc_multi_buff_crc(IOVecs *buffers)
//{
//    uint16_t crc_ret = crc32(0L, Z_NULL, 0);
//    LOOP(buffers->count, i) {
//        size_t addition = 0;
//        if (i == 0) {
//            // should skip the header
//            addition = MirroredIO::get_header_size();
//        }
//
//        crc_ret = crc32(crc_ret, (P::byte*)buffers->iovecs[i].iov_base + addition,
//                    buffers->iovecs[i].iov_len + addition);
//    }
//
//    return crc_ret;
//}

void MIO::internal_read(MirroredAddressToken address, UnifiedBuff *buff,
                        bool has_wlock, P::FiberSync::Future *future, bool async)
{
    ASSERT_NOT_NULL(buff);
    ASSERT_NOT_NULL(future);

    Reader* reader = _readers.alloc();
    reader->init(address, buff, &_mio_agent, &_readers, &_writers, &_future_pool, has_wlock, future);
    if (async) {
        P::Fiber::init(_fiber_group_id, runner<MIO::Reader>, (void*)reader, false);
    } else {
        reader->run();
    }
}

bool MIO::read(MirroredAddressToken address, IOVecs *buffers, P::FiberSync::FutureRes<bool> *future)
{
    UnifiedBuff buff;
    buff.protected_op = false;
    buff.scatter = buffers;

    P::FiberSync::FutureRes<bool> future_res;
    bool async = true;

    if (future == nullptr) {
        async = false;
        future = &future_res;
        future->init();
        future_res.res = true;
    }

    internal_read(address, &buff, false, (P::FiberSync::Future *)future, async);
    return future->res;
}

MIO::ReadRet MIO::protected_read(MirroredAddressToken address, Buffer *mio_buff,
                                 bool has_wlock, P::FiberSync::FutureRes<ReadRet> *future)
{
    UnifiedBuff buff;
    buff.protected_op = true;
    buff.prot_buff = mio_buff;

    P::FiberSync::FutureRes<ReadRet> future_res;
    bool async = true;

    if (future == nullptr) {
        async = false;
        future = &future_res;
        future->init();
        future_res.res = ReadRet::Success;
    }

    internal_read(address, &buff, has_wlock, (P::FiberSync::Future *)future, async);
    return future->res;
}

bool MIO::internal_write(MirroredAddressToken address, UnifiedBuff *buff, bool protected_write,
                                P::FiberSync::FutureRes<bool> *finalized_future,
                                P::FiberSync::FutureRes<bool> *committed_future)
{
    // operation is either fully sync (no futures) or async and then a finalization wait operation is mandatory.
    ASSERT(committed_future == nullptr || finalized_future != nullptr);
    bool should_perform_async = (finalized_future != nullptr);

    P::FiberSync::FutureRes<bool> future;
    if (!should_perform_async) {
        future.init();
        finalized_future = &future;
    }
    finalized_future->res = true;

    MIO::Writer* writer = _writers.alloc();
    writer->init(address, buff, &_mio_agent, &_writers, &_future_pool, finalized_future, committed_future);
    if (should_perform_async) {
        ASSERT_NOT_NULL(P::Fiber::init(_fiber_group_id, runner<MIO::Writer>, (void*)writer, false));
    } else {
        writer->run();
    }

    return finalized_future->res;
}

// Not thread safe! should be performed under an appropriate lock.
bool MIO::write(MirroredAddressToken address, IOVecs *buffers, P::FiberSync::FutureRes<bool> *finalized_future)
{
    UnifiedBuff buff;
    buff.protected_op = false;
    buff.scatter = buffers;
    return internal_write(address, &buff, false, finalized_future);
}

// Not thread safe! should be performed under an appropriate lock.
bool MIO::protected_write(MirroredAddressToken address, Buffer *mio_buff,
                                 P::FiberSync::FutureRes<bool> *finalized_future,
                                 P::FiberSync::FutureRes<bool> *committed_future)
{
    UnifiedBuff buff;
    buff.protected_op = true;
    buff.prot_buff = mio_buff;

    return internal_write(address, &buff, true, finalized_future, committed_future);
}

/// Mirrored locking ///

bool MIO::is_live_worker(WorkerID worker_id)
{
    // todo: implement
//    PANIC("Not Implemented!");
    return true;
}

bool MIO::atomic_op(MIOAgent::MappingSet *map_set, P::Index dev_idx, WorkerID worker_id, bool lock, bool blocking)
{
    PhysAddr curr_addr;
    map_set->at(dev_idx, &curr_addr);
    MemIO *mem_dev = dynamic_cast<MemIO*>(curr_addr.dev);
    WorkerID expected_old_value = lock ? Unlocked : worker_id;
    WorkerID new_value = lock ? worker_id : Unlocked;

    while (true) {
        WorkerID old_value;
        if (!mem_dev->compare_and_swap(curr_addr.byte_offset, new_value, expected_old_value, &old_value)) {
            // Todo: handle failures
            PANIC();
        }
        if (expected_old_value == old_value) {
            break;
        }

        ASSERT(lock, "Worker " << worker_id << " unlocking a lock that is not locked by the worker?! lock holds a value of " << old_value);

        if (is_live_worker(old_value)) {
            // make sure that all previous devices are dead
            // meaning- if we locked a device that is still living we should be the only locker.

            // wish we could do this assert but there's no guarantee that the local agent is up to date...
//            LOOP_TYPE(P::Index, dev_idx, secondary_idx) {
//                PhysAddr prev_addr;
//                map_set->at(secondary_idx, &prev_addr);
//                ASSERT(!_agent->is_device_alive(prev_addr.dev));
//            }

            if (!blocking) {
                return false;
            }

            // Todo: make this more intelligent:
            //       * increase wait interval - like in retry loop. begin with single yields and go on from there.
            //       * implement a timeout- when expires, notify control and log and then..? Don't know whether we should panic or not.
            P::TimerQueues::fast_sleep(wait_interval);
        } else {
            expected_old_value = old_value;
        }
    }

    return true;
}

// Todo: do we need an async version here as well?
bool MIO::internal_lock(MirroredAddressToken address, WorkerID worker_id, bool lock, bool blocking)
{
    // Try unlock makes no sense...
    ASSERT(lock || blocking);
    ASSERT(address.supports_atomic_ops());
    ASSERT(worker_id != Unlocked);

    bool success = true;
    MIOAgent::MappingSet map_set;
    _mio_agent.start_write(address, sizeof(WorkerID), &map_set);
    uint32_t set_size = map_set.size();
    LOOP_TYPE(P::Index, set_size, i) {
        P::Index dev_idx = lock ? i : set_size - i - 1;
        if (!atomic_op(&map_set, dev_idx, worker_id, lock, blocking)) {
            success = false;
            break;
        }
    }

    _mio_agent.done_write(address, &map_set);
    return success;
}

void MIO::lock(MirroredAddressToken address, WorkerID worker_id)
{
    bool ret = internal_lock(address, worker_id, true, true);
    ASSERT(ret);
}

bool MIO::trylock(MirroredAddressToken address, WorkerID worker_id)
{
    return internal_lock(address, worker_id, true, false);
}

void MIO::unlock(MirroredAddressToken address, WorkerID worker_id)
{
    bool ret = internal_lock(address, worker_id, false, true);
    ASSERT(ret);
}


//////////////////////////////////////////////////
///////////////// Buffer /////////////////////////
//////////////////////////////////////////////////

void MIO::Buffer::init(P::byte buffer[], size_t len)
{
    // not checking for alignment in the buffer init since in some cases the buffer is used for memory operations
    // which does not require alignment
//    ASSERT_EQUAL((size_t)buffer % DevIO::O_DIRECT_ALIGNMENT, 0, "MIOBuffer must be aligned");
//    ASSERT_EQUAL(len % DevIO::O_DIRECT_ALIGNMENT, 0, "MIOBuffer size must be aligned");
    ASSERT_OP(len, >, MIO::get_header_size(), "MIOBuffer must be bigger than MIO header");

    _vec.iov_base = buffer;
    _vec.iov_len = len;
}

//////////////////////////////////////////////////
///////////////// Writer /////////////////////////
//////////////////////////////////////////////////

void MIO::Writer::init(MirroredAddressToken address, UnifiedBuff* buff, MIOAgent *agent, P::ObjectPool<Writer> *pool,
                       P::AtomicPool<BaseIO::Future> *future_pool, P::FiberSync::FutureRes<bool> *finalized_future,
                       P::FiberSync::FutureRes<bool> *committed_future)
{
    _committed_future = committed_future;
    _future_pool = future_pool;
    IOer::init(address, buff, agent, pool, finalized_future);
}

void MIO::Writer::set_header(P::byte *header_buff OUT, bool committed)
{
    Header *header = (Header*)header_buff;
    header->is_committed = committed;
}

void MIO::Writer::fill_header(bool committed)
{
    Header *header = (Header*)_buff.prot_buff->get_mio_vec()->iov_base;
    header->CRC = MIO::calc_buff_crc(_buff.prot_buff);
    set_header((P::byte*)header, committed);
}

bool MIO::Writer::single_write(BaseIO *dev, IOVecs *buffers, Baddr address, MIOAgent *agent, BaseIO::Future *future)
{
    Baddrs target_baddrs;
    target_baddrs.count = 1;
    target_baddrs.baddrs = &address;

    // todo: reconsider retry param values.
    bool too_many_times;
    RETRY_LOOP(too_many_times, write_retry_params, P::Fiber::yield,
        if (dev->write_scatter(buffers, &target_baddrs, future)) {
            break;
        }
        if (!agent->is_device_alive(dev)) {
            // It's OK to skip this device
            // TODO: add info to trace
            PT_WARN(DATA, "Skipping a removed device during write");
            break;
        }
    )

    return !too_many_times;
}

bool MIO::Writer::concurrent_write(MIOAgent::MappingSet *phys_address_set, P::Index device_count, IOVecs *buffers)
{
    bool success = true;
    BaseIO::Future *futures[device_count];
    BaseIO *devices[device_count];
    P::FiberSync::Future *future_base_ptrs[device_count];
    _future_pool->alloc_multiple(futures, device_count);

    P::Index phys_idx = 0;
    PhysAddr curr_addr;

    size_t submitted_ios;
    for (submitted_ios = 0; (submitted_ios < device_count); ++submitted_ios) {
        phys_address_set->at(phys_idx, &curr_addr);
        devices[submitted_ios] = curr_addr.dev;

        futures[submitted_ios]->init();
        future_base_ptrs[submitted_ios] = (BaseIO::Future *)futures[submitted_ios];
        if (!single_write(curr_addr.dev, buffers, curr_addr.byte_offset, _agent,
                          futures[submitted_ios])) {
            success = false;
            break;
        }
    }

    BaseIO::Future::wait_all(future_base_ptrs, submitted_ios);

    LOOP(submitted_ios, i) {
        // we only fail when an IO to a live device fails.
        success = success && (futures[i]->res || !_agent->is_device_alive(devices[i]));
        futures[i]->destroy();
    }

    _future_pool->free_multiple(futures, device_count);

    return success;
}

bool MIO::Writer::write_with_header(MIOAgent::MappingSet *phys_address_set)
{
    // This method is resilient under the assumption that a single device write operation
    // is atomic (no partial write when crashing).
    // We may remove this assert and handle the partial crash writes with crc detection and fix from redundancy.
    // Note that when fixes are done lazily we are exposed to corruption
    // (several writes with no reads- crashing in devices n, n-1, ..., 1 - by that order)
    ASSERT_OP(_buff.prot_buff->get_mio_vec()->iov_len, <=, AddressToken::atomic_block_size_of_type(_address.token_type));

    bool success = true;
    fill_header(false);
    IOVecs vecs;
    vecs.count = 1;
    vecs.iovecs = _buff.prot_buff->get_mio_vec();
    PhysAddr curr_addr;
    LOOP_TYPE(P::Index, phys_address_set->size() - 1, dev_idx) {
        phys_address_set->at(dev_idx, &curr_addr);
        if (!single_write(curr_addr.dev, &vecs, curr_addr.byte_offset, _agent)) {
            success = false;
            break;
        }
    }

    if (success) {
        // last write is a committed write
        set_header((P::byte*) (vecs.iovecs[0].iov_base), true);
        phys_address_set->at(phys_address_set->size() - 1, &curr_addr);
        success &= single_write(curr_addr.dev, &vecs, curr_addr.byte_offset, _agent);
    }

    if (_committed_future != nullptr) {
        _committed_future->res = success;
        _committed_future->set();
    }

    if (success) {
        // should perform n-1 header updates asynchronously
        IOVec header_buff;
        header_buff.iov_base = vecs.iovecs[0].iov_base;
        header_buff.iov_len = P::round_to(MIO::get_header_size(), DevIO::O_DIRECT_ALIGNMENT);
        ASSERT_OP(header_buff.iov_len, <=, vecs.iovecs[0].iov_len);

        IOVecs header_buffers;
        header_buffers.count = 1;
        header_buffers.iovecs = &header_buff;

        success &= concurrent_write(phys_address_set, phys_address_set->size() - 1, &header_buffers);
    }

    return success;
}

void MIO::Writer::run()
{
    ASSERT(_initialized);
    MIOAgent::MappingSet phys_address_set;
    _agent->start_write(_address, _buff.get_size(), &phys_address_set);

    bool res = _buff.protected_op ?
        write_with_header(&phys_address_set) :
        concurrent_write(&phys_address_set, phys_address_set.size(), _buff.scatter);

    if (_future != nullptr) {
        P::FiberSync::FutureRes<bool> *final_future = (P::FiberSync::FutureRes<bool> *)(_future);
        final_future->res = res;
        final_future->set();
    }

    _agent->done_write(_address, &phys_address_set);
    destroy();
}



//////////////////////////////////////////////////
///////////////// Reader /////////////////////////
//////////////////////////////////////////////////

void MIO::Reader::init(MirroredAddressToken address, UnifiedBuff *buff, MIOAgent *agent, P::ObjectPool<Reader> *pool,
          P::ObjectPool<Writer> *writers, P::AtomicPool<BaseIO::Future> *future_pool, bool has_wlock,
                       P::FiberSync::Future *future)
{
    _writers = writers;
    _future_pool = future_pool;
    _has_wlock = has_wlock;
    IOer::init(address, buff, agent, pool, future);
}

bool MIO::Reader::is_data_valid(Buffer *mio_buff)
{
    Header *header = (Header*)mio_buff->get_mio_vec()->iov_base;
    Header calculated_header;
    calculated_header.CRC = calc_buff_crc(mio_buff);
    return (header->CRC == calculated_header.CRC);
}

bool MIO::Reader::is_data_committed(Buffer *mio_buff)
{
    Header *header = (Header*)mio_buff->get_mio_vec()->iov_base;
    return (header->is_committed == 1);
}

bool MIO::Reader::recover_corrupted_data(MirroredAddressToken address, Buffer *mio_buff OUT)
{
    IOVecs buffers;
    buffers.count = 1;
    buffers.iovecs = mio_buff->get_mio_vec();

    MIOAgent::MappingSet phys_addr_set;
    _agent->start_write(address, buffers.total_length(), &phys_addr_set);
    P::Index read_idx = 0;
    if(!read_internal(address, &buffers, &phys_addr_set, &read_idx)) {
        _agent->done_write(address, &phys_addr_set);
        return false;
    }

    P::Index corruption_count = 0;
    P::Index corrupted_devices[phys_addr_set.size()];
    while (!is_data_valid(mio_buff)) {
        corrupted_devices[corruption_count] = read_idx;
        corruption_count++;
        read_idx++;

        if(!read_internal(address, &buffers, &phys_addr_set, &read_idx, false)) {
            _agent->done_write(address, &phys_addr_set);
            return false;
        }
    }

    if (!is_data_committed(mio_buff)) {
        _agent->done_write(address, &phys_addr_set);
        // leaving the write to the natural "roll forward" flow of read
        return true;
    }

    while (corruption_count > 0) {
        corruption_count--;
        PhysAddr phys;
        phys_addr_set.at(corrupted_devices[corruption_count], &phys);
        if (!Writer::single_write(phys.dev, &buffers, phys.byte_offset, _agent)) {
            _agent->done_write(address, &phys_addr_set);
            return false;
        }
    }

    _agent->done_write(address, &phys_addr_set);
    return true;
}

bool MIO::Reader::read_internal(MirroredAddressToken address, IOVecs *buffers, MIOAgent::MappingSet *phys_addr_set,
                                P::Index *read_idx INOUT, bool wrap_around)
{
    ASSERT_NOT_NULL(phys_addr_set);
    ASSERT_NOT_NULL(read_idx);

    // make sure that read_idx is not beyond bounds
    if (*read_idx >= phys_addr_set->size()) {
        PT_WARN(DATA, "Attempted to initiate a read operation to device on index %d while section is in %u devices.",
                *read_idx, phys_addr_set->size());
        ASSERT(wrap_around);
        // This cannot happen for protected reads (where we start reading at idx 0)
        // so we may change the initial idx when needed.
        *read_idx = *read_idx % phys_addr_set->size();
    }

    Baddrs baddrs;
    baddrs.count = 1;
    P::Index last_read_idx = wrap_around ? *read_idx : 0;
    PhysAddr phys;
    bool done_IO = false;
    bool too_many_retries = false;
    do {
        if (*read_idx >= phys_addr_set->size()) {
            PANIC("All devices holding section " << address.section_id <<" are dead! Data might be lost!!!");
        }
        bool may_read;
        phys_addr_set->at(*read_idx, &phys, &may_read);
        RETRY_LOOP(too_many_retries, read_retry_params, P::Fiber::yield,
            baddrs.baddrs = &phys.byte_offset;
            if (may_read && phys.dev->read_scatter(buffers, &baddrs)) {
                done_IO = true;
                break;
            }

            if (!may_read || _agent->is_device_alive(phys.dev)) {
                *read_idx = (*read_idx + 1) % phys_addr_set->size();
                if (*read_idx == last_read_idx) {
                    PANIC("All devices holding section " << address.section_id <<" are dead or corrupted! Data might be lost!!!");
                }
                break;
            }
            // TODO: notify Control + improve LOG (display some sort of a device ID)
            PT_ERROR(DATA, "A read operation had failed although device is considered to be alive");
        )
    } while (!done_IO && !too_many_retries);

    return done_IO;
}

void MIO::Reader::read(IOVecs *buffers, P::FiberSync::FutureRes<bool> *future)
{
    ASSERT_NOT_NULL(future);

    MIOAgent::MappingSet phys_addr_set;
    _agent->start_read(_address, &phys_addr_set);

    // Todo: randomize this
    P::Index start_idx = 1;

    // Todo: We may want to pass a "may skip live devices" flag
    //       to avoid being stuck on a single device retry loop for no reason
    future->res = read_internal(_address, buffers, &phys_addr_set, &start_idx);
    _agent->done_read(_address, &phys_addr_set);
}

void MIO::Reader::read_with_header(Buffer *mio_buff, P::FiberSync::FutureRes<MIO::ReadRet> *future)
{
    ASSERT_NOT_NULL(future);

    IOVecs buffers;
    buffers.count = 1;
    buffers.iovecs = mio_buff->get_mio_vec();

    MIOAgent::MappingSet phys_addr_set;
    _agent->start_read(_address, &phys_addr_set);
    // Note: We must read the first device.
    // that is the only way we are sure the stripe is holding the same data in all devices
    // and that there is no need for a fix.
    P::Index read_idx = 0;
    bool read_success = read_internal(_address, &buffers, &phys_addr_set, &read_idx);
    _agent->done_read(_address, &phys_addr_set);
    if (!read_success) {
        future->res = ReadRet::IOError;
        return;
    }

    if (!is_data_valid(mio_buff)) {
        // Todo: fix this log up (should add some device ID) + Notify control!
        PT_WARN(DATA, "Detected data corruption in device BLA. Attempting to recover using mirrored copies!");
        if (!_has_wlock) {
            future->res = ReadRet::RequiresWriteLock;
            return;
        }

        if(!recover_corrupted_data(_address, mio_buff)) {
            future->res = ReadRet::IOError;
            return;
        }
    }

    if (!is_data_committed(mio_buff)) {
        if (!_has_wlock) {
            future->res = ReadRet::RequiresWriteLock;
            return;
        }

        // we are under lock and data is not committed. we may fix this stripe:
        // Todo: consider avoiding the extra CRC calculation here (and extra write...)
        Writer *writer = (Writer*)_writers->alloc();
        UnifiedBuff buff;
        buff.protected_op = true;
        buff.prot_buff = mio_buff;
        writer->init(_address, &buff, _agent, _writers, _future_pool);
        writer->run();
    }
    future->res = ReadRet::Success;
}


void MIO::Reader::run()
{
    ASSERT(_initialized);

    MIOAgent::MappingSet phys_address_set;
    _agent->start_read(_address, &phys_address_set);

    if (_buff.protected_op) {
        read_with_header(_buff.prot_buff, (P::FiberSync::FutureRes<MIO::ReadRet> *)_future);
    } else {
        read(_buff.scatter, (P::FiberSync::FutureRes<bool> *)_future);
    }

    _future->set();
    _agent->done_read(_address, &phys_address_set);
    destroy();
}

}
