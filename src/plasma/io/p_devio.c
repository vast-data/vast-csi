/* Copyright (C) Vast Data Ltd. */
#define _GNU_SOURCE

#include "p_devio.h"
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>

struct PDevIOFuture {
    PFuture future;
    uint32_t io_count;
};

static void p_pio_init(PIO *pio)
{
    io_set_callback(&pio->io, NULL);
    pio->io_future = NULL;
}

bool p_devio_init(PDevIO *devio OUT, const char dev_name[], uint32_t iodepth, PAtomicPool *iopool)
{
    devio->iodepth = iodepth;
    devio->iopool = iopool;
    p_sem_init(&devio->available_ios, iodepth);

    devio->ctx = 0;
    int setup_ret = io_setup((int) iodepth, &devio->ctx);
    if (setup_ret != 0) {
        P_PANIC(/* TODO: informative string with the value of setup_ret
                         (negated errno in this case - might use strerror(-setup_ret)) */);
    }

    devio->io_provider = NULL;

    P_ASSERT(strnlen(dev_name, PATH_MAX) < PATH_MAX);
    strncpy(devio->dev_name, dev_name, PATH_MAX);
    int open_flags = O_RDWR | O_CREAT | O_DIRECT;
    devio->file_desc = open(devio->dev_name, open_flags);
    if (devio->file_desc == -1) {
        // P_TRACE_ERR(/* TODO: informative string with the value of errno - might use strerror() / perror()) */);
        return false;
    }

    return true;
}

void p_devio_set_ioprovider(PDevIO *devio, PIOProvider *io_provider)
{
    P_ASSERT(devio == NULL);
    devio->io_provider = io_provider;
}

static void allocate_ios(PDevIO *devio, struct iocb *ios[], uint32_t count, PDevIOFuture *io_future)
{
    bool was_idle = (devio->available_ios.value == devio->iodepth);
    p_sem_dec(&devio->available_ios, count);
    PIndex element_idices[count];
    p_atomic_pool_alloc_multiple(devio->iopool, element_idices, count);
    LOOP(count, i) {
        PIO *io = (PIO*)p_atomic_pool_index_to_element(devio->iopool, element_idices[i]);
        p_pio_init(io);
        io->io_future = io_future;
        ios[i] = &io->io;
    }

    if (was_idle) {
        P_DEBUG_ASSERT(devio->io_provider != NULL);
        p_io_provider_enable_polling(devio->io_provider, devio);
    }
}

static void io_prep(PDevIO *devio, struct iocb *io OUT, IOVecs *buffers, Baddr dev_offset, bool is_write)
{
    if (buffers->count == 1) {
        (is_write ? io_prep_pwrite : io_prep_pread)
                (io, devio->file_desc, buffers->iovecs[0].iov_base, buffers->iovecs[0].iov_len, (long long)dev_offset);
    } else {
        (is_write ? io_prep_pwritev : io_prep_preadv)
                (io, devio->file_desc, buffers->iovecs, (int)buffers->count, (long long)dev_offset);
    }
}

static void p_devio_handle_io_done(PDevIO *devio, struct iocb *iocb_done)
{
    PIO *io =  MEMBER2OBJECT(iocb_done, PIO, io);
    P_DEBUG_ASSERT(io->io_future != NULL);
    P_ASSERT(io->io_future->io_count > 0);

    io->io_future->io_count--;
    if (io->io_future->io_count == 0) {
        p_future_set(&io->io_future->future);
    }

    io->io_future = NULL;
    p_atomic_pool_free(devio->iopool, (void*)io);
}

void p_devio_poll_events(PDevIO *devio)
{
    const long active_ios = devio->iodepth - devio->available_ios.value;
    struct io_event events[active_ios];

    P_ASSERT(active_ios > 0);

    int ios_done;
    RETRY_LOOP(io_polling, 100, 5, 1000,
        ios_done = io_getevents(devio->ctx, 0, active_ios, events, NULL);
        if (ios_done >= 0) {
            break;
        }
        if ((ios_done < 0) && (ios_done != -EINTR)) {
            P_PANIC();
        }
    )

    // Todo: should we remove this condition and allow empty flow?
    if(ios_done == 0) {
        return;
    }

    LOOP_TYPE(uint32_t, ios_done, event_index) {
        p_devio_handle_io_done(devio, events[event_index].obj);
    }

    p_sem_inc(&devio->available_ios, (uint32_t)ios_done);
    if (devio->iodepth == devio->available_ios.value) {
        P_DEBUG_ASSERT(devio->io_provider != NULL);
        // no more active ios
        p_io_provider_disable_polling(devio->io_provider, devio);
    }
}

static void submit_ios(PDevIO *devio, struct iocb **ios_ptr, uint32_t io_count)
{
    RETRY_LOOP(io_submition, 100, 5, 1000,
        int submit_ret = io_submit(devio->ctx, io_count, ios_ptr);
        if (submit_ret == (int) io_count) {
            break;
        } else {
            if ((submit_ret < 0) && (submit_ret != -EAGAIN)) {
                P_PANIC();
            }
            if (submit_ret > 0) {
                // several first IO's were submitted.
                // retry the rest.
                P_ASSERT(submit_ret < (int )io_count);
                io_count -= (uint32_t) submit_ret;
                ios_ptr += submit_ret;
            }
        }
    )
}

static IODevRet
p_devio_perform_scattered_io(PDevIO *devio, IOVecs buffers[], Baddrs *dev_offsets, bool is_write, PDevIOFuture *io_future)
{
    const uint32_t io_count = dev_offsets->count;
    // Todo: is this a proper size on the stack? - should set a maximum defined size here
    struct iocb *ios[io_count];

    bool blocking = false;
    if (io_future == NULL) {
        blocking = true;
        io_future = alloca(sizeof(io_future));
    }

    io_future->io_count = io_count;
    p_future_init(&io_future->future, NULL);

    allocate_ios(devio, ios, io_count, io_future);
    LOOP(io_count, io_index) {
        io_prep(devio, ios[io_index], &buffers[io_index], dev_offsets->baddrs[io_index], is_write);
    }

    submit_ios(devio, ios, io_count);

    if (blocking) {
        p_devio_wait(devio, io_future);
    }

    return P_IODEV_SUCCESS;
}

IODevRet p_devio_write_scatter(PDevIO *devio, IOVecs buffers[], Baddrs *target_baddrs, PDevIOFuture *io_future)
{
    return p_devio_perform_scattered_io(devio, buffers, target_baddrs, true, io_future);
}

IODevRet p_devio_read_scatter(PDevIO *devio, IOVecs buffers[], Baddrs *source_baddrs, PDevIOFuture *io_future)
{
    return p_devio_perform_scattered_io(devio, buffers, source_baddrs, false, io_future);
}

static IODevRet p_devio_perform_io(PDevIO *devio, IOVec *buffer, Baddr target_baddr, bool is_write, PDevIOFuture *io_future)
{
    IOVecs iovecs;
    iovecs.count = 1;
    iovecs.iovecs = buffer;

    Baddrs baddrs;
    baddrs.count = 1;
    baddrs.baddrs = &target_baddr;

    return p_devio_perform_scattered_io(devio, &iovecs, &baddrs, is_write, io_future);
}

IODevRet p_devio_write(PDevIO *devio, IOVec *buffer, Baddr target_baddr, PDevIOFuture *io_future)
{
    return p_devio_perform_io(devio, buffer, target_baddr, true, io_future);
}

IODevRet p_devio_read(PDevIO *devio, IOVec *buffer, Baddr source_baddr, PDevIOFuture *io_future)
{
    return p_devio_perform_io(devio, buffer, source_baddr, false, io_future);
}

void p_devio_wait(PDevIO *devio UNUSED, PDevIOFuture *io_future)
{
    if (p_future_is_set(&io_future->future)) {
        return;
    }

    p_future_wait(&io_future->future);
    P_ASSERT(io_future->io_count == 0);
}

void p_devio_destroy(PDevIO *devio)
{
    // Todo: Should we perform a last polling operation for a graceful shutdown?
    P_ASSERT(devio->available_ios.value == devio->iodepth);
    io_destroy(devio->ctx);
}
