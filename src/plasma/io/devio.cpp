/* Copyright (C) Vast Data Ltd. */

#include "devio.hpp"
#include <fcntl.h>
#include <errno.h>
#include <linux/fs.h>
#include <sys/ioctl.h>

namespace P {

static const RetryParams io_submit_retry_params = { .max_spinning_attempts = 100, .attempts_per_yield = 5, .max_attempts = 1000 };
static const RetryParams io_poll_retry_params = { .max_spinning_attempts = 100, .attempts_per_yield = 5, .max_attempts = 1000 };

bool DevIO::init(const char dev_name[], uint32_t iodepth, AtomicPool *iopool, size_t device_size)
{
    _iodepth = iodepth;
    _iopool = iopool;
    p_sem_init(&_available_ios, iodepth);

    _ctx = 0;
    int setup_ret = io_setup((int) iodepth, &_ctx);
    if (unlikely(setup_ret != 0)) {
        P_PANIC(/* TODO: informative string with the value of setup_ret
                         (negated errno in this case - might use strerror(-setup_ret)) */);
    }

    _io_provider = NULL;

    P_ASSERT(strnlen(dev_name, PATH_MAX) < PATH_MAX);
    strncpy(_dev_name, dev_name, PATH_MAX);
    int open_flags = O_RDWR | O_DIRECT;
    _file_desc = open(_dev_name, open_flags);
    if (unlikely(_file_desc == -1)) {
        // P_TRACE_ERR(/* TODO: informative string with the value of errno - might use strerror() / perror()) */);
        return false;
    }

    if (device_size == 0) {
        int ret = ioctl(_file_desc, BLKGETSIZE64, &device_size);
        P_ASSERT(ret != -1);
    }

    _size = device_size;

    return true;
}

void DevIO::set_ioprovider(IOProvider *io_provider)
{
    P_ASSERT(_io_provider == NULL);
    _io_provider = io_provider;
}

size_t DevIO::io_byte_count(struct iocb *ios)
{
    switch (ios->aio_lio_opcode) {
    case IO_CMD_PREAD:
    case IO_CMD_PWRITE:
        return ios->u.c.nbytes;
    case IO_CMD_PREADV:
    case IO_CMD_PWRITEV:
        break;
    default:
        P_PANIC();
    }

    size_t ret_size = 0;
    IOVec *iovec = (IOVec*) ios->u.c.buf;
    LOOP(ios->u.c.nbytes, i) {
        ret_size += iovec[i].iov_len;
    }

    return ret_size;
}

void DevIO::allocate_ios(struct iocb *ios[], uint32_t count, DevIO::Future *io_future)
{
    bool was_idle = (_available_ios.value == _iodepth);
    p_sem_dec(&_available_ios, count);
    PIndex element_idices[count];
    _iopool->alloc_multiple(element_idices, count);
    LOOP(count, i) {
        IO *io = (IO*)_iopool->index_to_element(element_idices[i]);
        io->io_future = io_future;
        ios[i] = &io->io;
    }

    if (was_idle) {
        P_DEBUG_ASSERT(_io_provider != NULL);
        _io_provider->enable_polling(this);
    }
}

void DevIO::io_prep(struct iocb *io OUT, IOVecs *buffers, Baddr dev_offset, bool is_write)
{
    if (buffers->count == 1) {
        (is_write ? io_prep_pwrite : io_prep_pread)
                (io, _file_desc, buffers->iovecs[0].iov_base, buffers->iovecs[0].iov_len, (long long)dev_offset);
    } else {
        (is_write ? io_prep_pwritev : io_prep_preadv)
                (io, _file_desc, buffers->iovecs, (int)buffers->count, (long long)dev_offset);
    }
}

void DevIO::handle_io_done(struct iocb *iocb_done)
{
    PIO *io =  MEMBER2OBJECT(iocb_done, PIO, io);
    P_DEBUG_ASSERT(io->io_future != NULL);
    P_ASSERT(io->io_future->io_count > 0);

    io->io_future->io_count--;
    if (io->io_future->io_count == 0) {
        p_future_set(&io->io_future->future);
    }

    io->io_future = NULL;
    _iopool->free((void*)io);
}

void DevIO::validate_io_event(struct io_event *event)
{
    size_t io_size = io_byte_count(event->obj);
    if (event->res != io_size) {
        // TODO: get res and possibly res2- log all that we can here
        IO *io =  MEMBER2OBJECT(event->obj, IO, io);
        PIndex index = _iopool->element_to_index(io);
        printf("IO error: index=%u, res=%ld, res2=%ld nbytes = %ld, opcode = %d\n",
               index, (long)event->res, (long)event->res2,
               (long)event->obj->u.c.nbytes, event->obj->aio_lio_opcode);
        io->io_future->res = ReturnCode::ERROR;
    }
}

void DevIO::poll_events()
{
    const long active_ios = _iodepth - _available_ios.value;
    struct io_event events[active_ios];

    P_ASSERT(active_ios > 0);

    int ios_done;
    RETRY_LOOP(io_poll_retry_params,
        ios_done = io_getevents(_ctx, 0, active_ios, events, NULL);
        if (ios_done >= 0) {
            break;
        }
        if (unlikely((ios_done < 0) && (ios_done != -EINTR))) {
            P_PANIC();
        }
    )

    // Todo: should we remove this condition and allow empty flow?
    if(ios_done == 0) {
        return;
    }

    LOOP_TYPE(uint32_t, ios_done, event_index) {
       validate_io_event(&events[event_index]);
       handle_io_done(events[event_index].obj);
    }

    p_sem_inc(&_available_ios, (uint32_t)ios_done);
    if (_iodepth == _available_ios.value) {
        P_DEBUG_ASSERT(_io_provider != NULL);
        // no more active ios
        _io_provider->disable_polling(this);
    }
}

void DevIO::submit_ios(struct iocb **ios_ptr, uint32_t io_count)
{
    RETRY_LOOP(io_submit_retry_params,
        int submit_ret = io_submit(_ctx, io_count, ios_ptr);
        if (submit_ret == (int) io_count) {
            break;
        } else {
            if (unlikely((submit_ret < 0) && (submit_ret != -EAGAIN))) {
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

void DevIO::validate_io(IOVecs buffers[], Baddrs *dev_offsets)
{
    LOOP(dev_offsets->count, baddr_idx) {
        size_t io_size = 0;
        LOOP (buffers[baddr_idx].count, iovec_idx) {
            // O_DIRECT limitations
            P_ASSERT(buffers[baddr_idx].iovecs[iovec_idx].iov_len % O_DIRECT_ALIGN == 0);
            P_ASSERT((size_t)buffers[baddr_idx].iovecs[iovec_idx].iov_base % O_DIRECT_ALIGN == 0);

            io_size += buffers[baddr_idx].iovecs[iovec_idx].iov_len;
        }

        // make sure the io doesn't go beyond device boundaries.
        P_ASSERT(dev_offsets->baddrs[baddr_idx] + io_size <= _size);
    }
}

DevIO::ReturnCode DevIO::perform_scattered_io(IOVecs buffers[], Baddrs *dev_offsets, bool is_write, DevIO::Future *io_future)
{
    validate_io(buffers, dev_offsets);

    const uint32_t io_count = dev_offsets->count;
    // Todo: is this a proper size on the stack? - should set a maximum defined size here
    struct iocb *ios[io_count];

    bool blocking = false;
    if (io_future == NULL) {
        blocking = true;
        io_future = (DevIO::Future*)alloca(sizeof(*io_future));
    }

    io_future->io_count = io_count;
    io_future->res = ReturnCode::SUCCESS;
    p_future_init(&io_future->future, NULL);

    allocate_ios(ios, io_count, io_future);
    LOOP(io_count, io_index) {
        io_prep(ios[io_index], &buffers[io_index], dev_offsets->baddrs[io_index], is_write);
    }

    submit_ios(ios, io_count);

    if (blocking) {
        return wait(io_future);
    }

    return ReturnCode::SUCCESS;
}

DevIO::ReturnCode DevIO::write_scatter(IOVecs buffers[], Baddrs *target_baddrs, DevIO::Future *io_future)
{
    return perform_scattered_io(buffers, target_baddrs, true, io_future);
}

DevIO::ReturnCode DevIO::read_scatter(IOVecs buffers[], Baddrs *source_baddrs, DevIO::Future *io_future)
{
    return perform_scattered_io(buffers, source_baddrs, false, io_future);
}

DevIO::ReturnCode DevIO::perform_io(IOVec *buffer, Baddr target_baddr, bool is_write, DevIO::Future *io_future)
{
    IOVecs iovecs;
    iovecs.count = 1;
    iovecs.iovecs = buffer;

    Baddrs baddrs;
    baddrs.count = 1;
    baddrs.baddrs = &target_baddr;

    return perform_scattered_io(&iovecs, &baddrs, is_write, io_future);
}

DevIO::ReturnCode DevIO::write(IOVec *buffer, Baddr target_baddr, DevIO::Future *io_future)
{
    return perform_io(buffer, target_baddr, true, io_future);
}

DevIO::ReturnCode DevIO::read(IOVec *buffer, Baddr source_baddr, DevIO::Future *io_future)
{
    return perform_io(buffer, source_baddr, false, io_future);
}

DevIO::ReturnCode DevIO::wait(DevIO::Future *io_future)
{
    p_future_wait(&io_future->future);
    P_ASSERT(io_future->io_count == 0);

    return io_future->res;
}

void DevIO::destroy()
{
    // Todo: Should we perform a last polling operation for a graceful shutdown?
    P_ASSERT(_available_ios.value == _iodepth);
    io_destroy(_ctx);
}

// Still not operational, yet it should be in the future...

//DevIO::ReturnCode DevIO::trim(Baddr base_offset, size_t block_count)
//{
//
//    off_t trim_ext[2];
//    trim_ext[0] = (off_t) base_offset;
//    trim_ext[1] = (off_t) block_count;
//
//    int ret = ioctl(_file_desc, /* IOCATADELETE / BLKDISCARD */, trim_ext);
//    if (ret < 0) {
//        P_PANIC();
//    }
//
//    return P_IODEV_SUCCESS;
//}

//void DevIO::flush()
//{
//    int ret = ioctl(_file_desc, /* FDFLUSH / BLKFLSBUF, 0 */);
//    if (ret < 0) {
//        P_PANIC();
//    }
//}
}
