/* Copyright (C) Vast Data Ltd. */

/*!
 * \file devio.hpp
 * \brief Performs block level IO to device.
 *
 * This is a wrapper of libaio that allows scatter -> scatter
 * Read and write.
 * It is uniquely mapped to a device.
 *
 */

#pragma once

#include <limits.h>
#include <libaio.h>
#include <sys/uio.h>

#include "base_io.hpp"
#include "io_provider.hpp"
#include "plasma/memory/atomic_pool.hpp"
#include "plasma/fiber/sync/sem.hpp"


namespace P {

namespace IO {

class IOProvider;

#define IO_BADDRS_MAX_COUNT 64

class DevIO : public BaseIO {
public:
    static const size_t O_DIRECT_ALIGNMENT = 512;

    class IO {
    public:
        struct iocb io;
        Future *io_future;
    };

    /*!
     * Initialize a PDevIO structure.
     * When finished with the PDevIO call destroy.
     * \param devio the structure to be initialized.
     * \param dev_name the device path.
     * \param iodepth the maximum value of concurrent pending ios for this device.
     * \param iopool the shared object pool holding items of type PIO.
     * \param device_size maximum address allowed for this device.
     *  When 0 is passed device size is auto determined (block device only).
     */
    bool WARN_UNUSED init(const char dev_name[], uint32_t iodepth, AtomicPool<IO> *iopool, size_t device_size);

    /*!
     * Poll for io done events and possibly release fibers that are IO pending.
     */
    void poll_events();

    /*!
     * Set an IOProvider object that performs polling over IO submissions.
     */
    void set_ioprovider(IOProvider *io_provider);

    /*!
     * Release PDevIO structure resources.
     * \param devio is the structure to be released.
     */
    void destroy();

    // Next is still not operational, yet it should be in the future...

    /*!
     * Performs trim/unmap of baddrs in the device.
     */
    //IODevRet trim(Baddr base_offset, size_t block_count);

    /*!
     * Performs flushing of the device.
     */
    //void flush();

private:

    static size_t io_byte_count(struct iocb *ios);

    void allocate_ios(struct iocb *ios[], uint32_t count, Future *io_future);

    void validate_io(IOVecs buffers[], Baddrs *dev_offsets);

    void io_prep(struct iocb *io OUT, IOVecs *buffers, Baddr dev_offset, bool is_write);

    bool WARN_UNUSED submit_ios(struct iocb **ios_ptr, uint32_t io_count);

    bool WARN_UNUSED perform_scattered_io(IOVecs buffers[], Baddrs *dev_offsets, bool is_write, Future *io_future);

    void handle_io_done(struct iocb *iocb_done);

    void validate_io_event(struct io_event *event);

    io_context_t _ctx;
    // Todo: should we have a different limitation for reads & writes?
    FiberSync::Sem _available_ios;
    int _file_desc;
    char _dev_name[PATH_MAX];
    AtomicPool<IO> *_iopool;
    IOProvider *_io_provider;
    size_t _size;    // in bytes.
    uint32_t _iodepth;
};

}
}
