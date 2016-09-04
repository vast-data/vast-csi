/* Copyright (C) Vast Data Ltd. */

/*!
 * \file memio_mock.hpp
 * \brief memory IO mock for testing
 *
 * Extends basic IO operations to support RDMA specific operations such as atomic operations.
 *
 */

#pragma once

#include "memio.hpp"

namespace P {

namespace IO {

class MemIOMock : public MemIO {
public:
    static const Baddr mock_address = 0;
    bool WARN_UNUSED compare_and_swap(Baddr address, uint64_t new_val, uint64_t exp_val, uint64_t* old_val OUT);

protected:
    bool WARN_UNUSED perform_scattered_io(IOVecs buffers[], Baddrs *dev_offsets, bool is_write, Future *io_future);

    uint64_t _val = 0;
};

}
}
