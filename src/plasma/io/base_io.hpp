/* Copyright (C) Vast Data Ltd. */

/*!
 * \file i_io.hpp
 * \brief IO common interface
 *
 * This is the common interface for performing IO to a local/remote block device / RDMA access
 *
 */

#pragma once

#include <limits.h>
#include <libaio.h>
#include <sys/uio.h>

#include "plasma/utils/io.hpp"
#include "plasma/fiber/sync/future_res.hpp"

namespace P {

namespace IO {

struct Baddrs {
    uint32_t count; // We allow a maximum of IO_BADDRS_MAX_COUNT target baddrs for a single IO. Limiting stack allocated structures.
    Baddr *baddrs;
};

class BaseIO {
public:

    class Future : public FiberSync::FutureRes<bool> {
        // Todo: if we allow this to be a bit less C+ we can override and extend wait_subset to perform the assert(io_count == 0) and remove BaseIO::wait
    public:
        uint32_t io_count;
    };

    /*!
     * Perform a scatter => scatter write operation
     * \param buffers an array of scatter_gather buffers containing data to be written.
     * \param target_baddrs a structure holding the collection of target device physical addresses to write to.
     *        target_baddrs->count is the length of buffers array.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    bool WARN_UNUSED write_scatter(IOVecs buffers[], Baddrs *target_baddrs, Future *io_future = nullptr);

    /*!
     * Perform a scatter => scatter read operation
     * \param buffers an array of scatter_gather buffers to be filled by the read operation.
     * \param source_baddrs a structure holding the collection of source device physical addresses from which the read is performed.
     *        source_baddrs->count is the length of buffers array.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    bool WARN_UNUSED read_scatter(IOVecs buffers[], Baddrs *source_baddrs, Future *io_future = nullptr);

    /*!
     * Perform a single buffer to a single address write operation
     * \param buffer scatter_gather buffers containing data to be written.
     * \param target_baddr target device physical addresses to write to.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    bool WARN_UNUSED write(IOVec *buffer, Baddr target_baddr, Future *io_future = nullptr);

    /*!
     * Perform a single address to single buffer read operation
     * \param buffer scatter_gather buffers to be filled by the read operation.
     * \param source_baddr source device physical addresses from which the read is performed.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    bool WARN_UNUSED read(IOVec *buffer, Baddr source_baddr, Future *io_future = nullptr);

    /*!
     * Wait on an IO operation.
     * \param io_future the token used when submitting the IO operation.
     */
    static bool WARN_UNUSED wait(Future *io_future)
    {
        // Todo: this method seems redundant.
        //       It only exists to perform the assert.
        //       We should either overwrite wait in DevIO::Future and perform the assert there (not real C+),
        //       or forget about this assert and simply remove this...

        // Todo: on the other hand we might want this method to perform a loop of try_wait() operations with a timeout
        //       to avoid an endless wait.. (don't know if that is even possible - where a submitted io never publishes any completion event)
        // in that case we need to make sure all io wait operations go through this method (which is not the case currently in mirrored_io)
        io_future->wait();
        ASSERT_EQUAL(io_future->io_count, 0);

        return io_future->res;
    }

    virtual ~BaseIO() = default;

protected:

    /*!
     * Perform a scatter => scatter IO operation
     * \param buffers an array of scatter_gather buffers containing data to be written or read to (depending on is_write).
     * \param dev_offsets a structure holding the collection of target device physical addresses to access.
     *        target_baddrs->count is the length of buffers array.
     * \param io_future the token to wait on for async execution. for sync operation set as nullptr.
     */
    virtual bool perform_scattered_io(IOVecs buffers[], Baddrs *dev_offsets, bool is_write, Future *io_future) = 0;

private:

    bool WARN_UNUSED perform_io(IOVec *buffer, Baddr target_baddr, bool is_write, Future *io_future);
};

}
}
