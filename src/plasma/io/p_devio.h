/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_devio.h
 * \brief Performs block level IO to device.
 *
 * This is a wrapper of libaio that allows scatter -> scatter
 * Read and write.
 * It is uniquely mapped to a device.
 *
 */

#pragma once

#include <p.h>

#include <limits.h>
#include <libaio.h>

// This will probably move to a more general location...
typedef uint64_t Baddr;

typedef struct iovec IOVec;

typedef struct PAtomicPool PAtomicPool;
typedef struct PIOProvider PIOProvider;

typedef struct PDevIO PDevIO;

struct PDevIO {
    io_context_t ctx;
    // Todo: should we have a different limitation for reads & writes?
    PSem available_ios;
    int file_desc;
    char dev_name[PATH_MAX];
    uint32_t iodepth;
    PAtomicPool *iopool;
    PIOProvider *io_provider;
};

typedef enum {
    P_IODEV_SUCCESS,
    P_IODEV_ERROR,
    P_IODEV_RETRY
} IODevRet;

typedef struct IOVecs {
    uint32_t count;
    IOVec* iovecs;
} IOVecs;

typedef struct PDevIOFuture PDevIOFuture;

typedef struct PIO {
    struct iocb io;
    PDevIOFuture *io_future;
} PIO;

#define PBADDRS_SIZE(baddr_count) (sizeof(Baddrs) + (baddr_count) * sizeof(Baddr)) UNUSED

typedef struct Baddrs {
    uint32_t count;
    Baddr* baddrs;
} Baddrs;

/*!
 * Initialize a PDevIO structure.
 * When finished with the PDevIO call p_devio_destroy.
 * \param devio the structure to be initialized.
 * \param dev_name the device path.
 * \param iodepth the maximum value of concurrent pending ios for this device.
 * \param iopool the shared object pool holding items of type PIO.
 */
bool p_devio_init(PDevIO *devio OUT, const char dev_name[], uint32_t iodepth, PAtomicPool *iopool) WARN_UNUSED;

/*!
 * Perform a scatter => scatter write operation
 * \param buffers an array of scatter_gather buffers containing data to be written.
 * \param target_baddrs a structure holding the collection of target device physical addresses to write to.
 *        target_baddrs->count is the length of buffers array.
 * \param io_future the token to wait on for async execution. for sync operation set as NULL.
 */
IODevRet p_devio_write_scatter(PDevIO *devio, IOVecs buffers[], Baddrs *target_baddrs, PDevIOFuture *io_future);

/*!
 * Perform a scatter => scatter read operation
 * \param buffers an array of scatter_gather buffers to be filled by the read operation.
 * \param source_baddrs a structure holding the collection of source device physical addresses from which the read is performed.
 *        source_baddrs->count is the length of buffers array.
 * \param io_future the token to wait on for async execution. for sync operation set as NULL.
 */
IODevRet p_devio_read_scatter(PDevIO *devio, IOVecs buffers[], Baddrs *source_baddrs, PDevIOFuture *io_future);

/*!
 * Perform a single buffer to a single address write operation
 * \param buffer scatter_gather buffers containing data to be written.
 * \param target_baddr target device physical addresses to write to.
 * \param io_future the token to wait on for async execution. for sync operation set as NULL.
 */
IODevRet p_devio_write(PDevIO *devio, IOVec* buffer, Baddr target_baddr, PDevIOFuture *io_future);

/*!
 * Perform a single address to single buffer read operation
 * \param buffer scatter_gather buffers to be filled by the read operation.
 * \param source_baddr source device physical addresses from which the read is performed.
 * \param io_future the token to wait on for async execution. for sync operation set as NULL.
 */
IODevRet p_devio_read(PDevIO *devio, IOVec* buffer, Baddr source_baddr, PDevIOFuture *io_future);

/*!
 * Wait on an IO operation.
 * \param io_future the token used when submitting the IO operation.
 */
void p_devio_wait(PDevIO *devio, PDevIOFuture *io_future);

/*!
 * Poll for io done events and possibly release fibers that are IO pending.
 */
void p_devio_poll_events(PDevIO *devio);

/*!
 * Set an IOProvider object that performs polling over IO submissions.
 */
void p_devio_set_ioprovider(PDevIO *devio, PIOProvider *io_provider);

/*!
 * Release PDevIO structure resources.
 * \param devio is the structure to be released.
 */
void p_devio_destroy(PDevIO *devio);

