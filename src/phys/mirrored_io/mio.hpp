/* Copyright (C) Vast Data Ltd. */

/*!
 * \file mio.hpp
 * \brief
 */
#pragma once

#include "mio_agent.hpp"
#include "plasma/utils/io.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/fiber/runnable.hpp"
#include "plasma/memory/object_pool.hpp"
#include "plasma/memory/atomic_pool.hpp"

namespace MirroredIO {

typedef uint64_t WorkerID;

class MIO {
public:
    enum class ReadRet {
        SUCCESS,
        REQUIRES_WRITE_LOCK,
        IO_ERROR,
        DATA_CORRUPTION,
    };

    static constexpr size_t DEFAULT_CONCURRENT_READERS = 10;
    static constexpr size_t DEFAULT_CONCURRENT_WRITERS = 10;
    static constexpr size_t DEFAULT_DEVICES_ASYNCLY_WRITTEN = 30;

    class Buffer {
    public:
        void init(P::byte buffer[], size_t len);
        P::byte *get_data() { return (P::byte*)_vec.iov_base + MIO::get_header_size(); }
        size_t get_data_size() { return _vec.iov_len - MIO::get_header_size(); }
        size_t get_raw_size() { return _vec.iov_len; }
        P::IO::IOVec *get_mio_vec() { return &_vec; }

    protected:
        P::IO::IOVec _vec;
    };

    void init(P::SiloId silo_id, ModuleId module_id, P::Index fiber_group_id, Control::DevAgent *dev_agent,
              size_t concurrent_readers, size_t concurrent_writers, size_t concurrent_devices_asyncly_written);
    void destroy();

    bool WARN_UNUSED read(Layout::MirroredAddress address, P::IO::IOVecs *buffers,
                          P::FiberSync::FutureRes<bool> *future = nullptr);
    ReadRet WARN_UNUSED protected_read(Layout::MirroredAddress address, Buffer *mio_buff,
                                       bool has_wlock, P::FiberSync::FutureRes<ReadRet> *future = nullptr);

    bool WARN_UNUSED write(Layout::MirroredAddress address, P::IO::IOVecs *buffers,
                           P::FiberSync::FutureRes<bool> *finalized_future = nullptr);
    bool WARN_UNUSED protected_write(Layout::MirroredAddress address, Buffer *mio_buff,
                                     P::FiberSync::FutureRes<bool> *finalized_future = nullptr,
                                     P::FiberSync::FutureRes<bool> *committed_future = nullptr);

    void lock(Layout::MirroredAddress address, WorkerID worker_id);
    bool WARN_UNUSED trylock(Layout::MirroredAddress address, WorkerID worker_id);
    void unlock(Layout::MirroredAddress address, WorkerID worker_id);

    static size_t get_header_size() { return sizeof(Header); }
    static uint16_t calc_buff_crc(Buffer *mio_buff);

    // TODO(ido): this is for testing only. Remove when not needed anymore. See ORION-81.
    MIOAgent* get_mio_agent() { return &_mio_agent; }

protected:

    struct Header {
        uint16_t is_committed   : 1;
        uint16_t CRC            : 15;
    };

    class UnifiedBuff {
    public:
        bool protected_op;
        union {
            P::IO::IOVecs *scatter;
            Buffer *prot_buff;
        };

        size_t get_size()
        {
            return protected_op ?
                   prot_buff->get_mio_vec()->iov_len :
                   scatter->total_length();
        }
    };

    template<typename T>
    class IOer : public IRunnable {
    public:
        void init(Layout::MirroredAddress address, UnifiedBuff *buff, MIOAgent *agent, P::ObjectPool<T> *pool,
                  P::FiberSync::Future *future = nullptr);
        void destroy();

    protected:
        MIOAgent *_agent;
        Layout::MirroredAddress _address;
        UnifiedBuff _buff;
        P::FiberSync::Future *_future;
        P::ObjectPool<T> *_pool;
        bool _initialized;
    };

    class Writer : public IOer<Writer> {
    public:
        void init(Layout::MirroredAddress address, UnifiedBuff* buff, MIOAgent *agent, P::ObjectPool<Writer> *pool,
                  P::AtomicPool<P::IO::BaseIO::Future> *future_pool,
                  P::FiberSync::FutureRes<bool> *finalized_future = nullptr,
                  P::FiberSync::FutureRes<bool> *committed_future = nullptr);
        void /* override */ run();

        void set_header(P::byte *header_buff INOUT, bool committed);
        void fill_header(bool committed);

        static bool WARN_UNUSED single_write(P::IO::BaseIO *dev, P::IO::IOVecs *buffers, P::IO::Baddr address,
                                             MIOAgent *agent, P::IO::BaseIO::Future *future = nullptr);
        bool WARN_UNUSED concurrent_write(MIOAgent::MappingSet *phys_address_set, P::Index device_count,
                                          P::IO::IOVecs *buffers);
        bool write_with_header(MIOAgent::MappingSet *phys_address_set);

    protected:
        P::FiberSync::FutureRes<bool> *_committed_future;
        P::AtomicPool<P::IO::BaseIO::Future> *_future_pool;
    };

    class Reader : public IOer<Reader> {
    public:
        void init(Layout::MirroredAddress address, UnifiedBuff *buff, MIOAgent *agent, P::ObjectPool<Reader> *pool,
                  P::ObjectPool<Writer> *writers, P::AtomicPool<P::IO::BaseIO::Future> *future_pool, bool has_wlock,
                  P::FiberSync::Future *future = nullptr);
        void /* override */ run();

        void read(P::IO::IOVecs *buffers, P::FiberSync::FutureRes<bool> *future);
        void read_with_header(Buffer *mio_buff, P::FiberSync::FutureRes<ReadRet> *future);

    protected:

        bool WARN_UNUSED is_data_valid(Buffer *mio_buff);
        bool WARN_UNUSED is_data_committed(Buffer *mio_buff);
        bool WARN_UNUSED recover_corrupted_data(Layout::MirroredAddress address, Buffer *mio_buff OUT);
        bool WARN_UNUSED read_internal(Layout::MirroredAddress address, P::IO::IOVecs *buffers,
                                       MIOAgent::MappingSet *phys_addr_set, P::Index *read_idx, bool wrap_around = true);

        bool _has_wlock;
        P::ObjectPool<Writer> *_writers;
        P::AtomicPool<P::IO::BaseIO::Future> *_future_pool;
    };

    static const WorkerID Unlocked = 0;

    bool WARN_UNUSED atomic_op(MIOAgent::MappingSet *map_set, P::Index dev_idx, WorkerID worker_id, bool lock,
                               bool blocking);
    bool WARN_UNUSED internal_lock(Layout::MirroredAddress address, WorkerID worker_id, bool lock, bool blocking);

    void internal_read(Layout::MirroredAddress address, UnifiedBuff *buff, bool has_wlock, P::FiberSync::Future *future, bool async);

    bool WARN_UNUSED internal_write(Layout::MirroredAddress address, UnifiedBuff *buff, bool protected_write,
                                    P::FiberSync::FutureRes<bool> *finalized_future = nullptr,
                                    P::FiberSync::FutureRes<bool> *committed_future = nullptr);

    bool WARN_UNUSED is_live_worker(WorkerID worker_id);



    P::ObjectPool<Writer> _writers;
    P::ObjectPool<Reader> _readers;
    Control::DevAgent *_dev_agent;
    MIOAgent _mio_agent;
    P::Index _fiber_group_id;
    P::AtomicPool<P::IO::BaseIO::Future> _future_pool;
};  // class MIO

template<typename T>
void MIO::IOer<T>::init(Layout::MirroredAddress address, UnifiedBuff *buff, MIOAgent *agent, P::ObjectPool<T> *pool,
          P::FiberSync::Future *future)
{
    _address = address;
    _buff = *buff;
    _agent = agent;
    _future = future;
    _pool = pool;
    _initialized = true;

}

template<typename T>
void MIO::IOer<T>::destroy()
{
    ASSERT((_future == nullptr) || _future->is_set());
    _initialized = false;
    _pool->free(dynamic_cast<T*>(this));
}

}
