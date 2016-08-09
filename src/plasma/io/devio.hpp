/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_devio.hpp
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

#include "plasma/utils/io.hpp"
#include "plasma/memory/atomic_pool.hpp"
#include "plasma/fiber/sync/future_res.hpp"
#include "plasma/fiber/sync/sem.hpp"
#include "io_provider.hpp"

namespace P {

class IOProvider;

#define IO_BADDRS_MAX_COUNT 64

typedef uint64_t Baddr;
struct Baddrs {
    uint32_t count; // We allow a maximum of IO_BADDRS_MAX_COUNT target baddrs for a single IO. Limiting stack allocated structures.
    Baddr *baddrs;
};

class DevIO {
public:
    static const size_t O_DIRECT_ALIGNMENT = 512;

    enum class ReturnCode : byte {
        SUCCESS,
        ERROR,
        RETRY
    };

    class Future : public FiberSync::FutureRes<ReturnCode> {
    public:
        uint32_t io_count;
    };

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
    bool WARN_UNUSED init(const char dev_name[],
                      uint32_t iodepth, AtomicPool<IO> *iopool, size_t device_size) WARN_UNUSED;

    /*!
     * Perform a scatter => scatter write operation
     * \param buffers an array of scatter_gather buffers containing data to be written.
     * \param target_baddrs a structure holding the collection of target device physical addresses to write to.
     *        target_baddrs->count is the length of buffers array.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    ReturnCode WARN_UNUSED write_scatter(IOVecs buffers[], Baddrs *target_baddrs, Future *io_future);

    /*!
     * Perform a scatter => scatter read operation
     * \param buffers an array of scatter_gather buffers to be filled by the read operation.
     * \param source_baddrs a structure holding the collection of source device physical addresses from which the read is performed.
     *        source_baddrs->count is the length of buffers array.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    ReturnCode WARN_UNUSED read_scatter(IOVecs buffers[], Baddrs *source_baddrs, Future *io_future);

    /*!
     * Perform a single buffer to a single address write operation
     * \param buffer scatter_gather buffers containing data to be written.
     * \param target_baddr target device physical addresses to write to.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    ReturnCode WARN_UNUSED write(IOVec *buffer, Baddr target_baddr, Future *io_future);

    /*!
     * Perform a single address to single buffer read operation
     * \param buffer scatter_gather buffers to be filled by the read operation.
     * \param source_baddr source device physical addresses from which the read is performed.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    ReturnCode WARN_UNUSED read(IOVec *buffer, Baddr source_baddr, Future *io_future);

    /*!
     * Wait on an IO operation.
     * \param io_future the token used when submitting the IO operation.
     */
    ReturnCode WARN_UNUSED wait(Future *io_future);

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

    void submit_ios(struct iocb **ios_ptr, uint32_t io_count);

    ReturnCode WARN_UNUSED perform_scattered_io(IOVecs buffers[], Baddrs *dev_offsets, bool is_write, Future *io_future);

    ReturnCode WARN_UNUSED perform_io(IOVec *buffer, Baddr target_baddr, bool is_write, Future *io_future);

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

};
