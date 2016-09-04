/* Copyright (C) Vast Data Ltd. */

#include "base_io.hpp"

namespace P {

namespace IO {

bool BaseIO::write_scatter(IOVecs buffers[], Baddrs *target_baddrs, BaseIO::Future *io_future)
{
    return perform_scattered_io(buffers, target_baddrs, true, io_future);
}

bool BaseIO::read_scatter(IOVecs buffers[], Baddrs *source_baddrs, BaseIO::Future *io_future)
{
    return perform_scattered_io(buffers, source_baddrs, false, io_future);
}

bool BaseIO::perform_io(IOVec *buffer, Baddr target_baddr, bool is_write, BaseIO::Future *io_future)
{
    IOVecs iovecs;
    iovecs.count = 1;
    iovecs.iovecs = buffer;

    Baddrs baddrs;
    baddrs.count = 1;
    baddrs.baddrs = &target_baddr;

    return perform_scattered_io(&iovecs, &baddrs, is_write, io_future);
}

bool BaseIO::write(IOVec *buffer, Baddr target_baddr, BaseIO::Future *io_future)
{
    return perform_io(buffer, target_baddr, true, io_future);
}

bool BaseIO::read(IOVec *buffer, Baddr source_baddr, BaseIO::Future *io_future)
{
    return perform_io(buffer, source_baddr, false, io_future);
}

}
}
