/* Copyright (C) Vast Data Ltd. */

#include "memio_mock.hpp"
#include "plasma/utils/assert.hpp"

namespace P {

namespace IO {

bool MemIOMock::compare_and_swap(Baddr address, uint64_t new_val, uint64_t exp_val, uint64_t* old_val OUT)
{
    ASSERT_EQUAL(address, mock_address);
    *old_val = _val;
    if (_val == exp_val) {
        _val = new_val;
    }

    return true;
}

bool MemIOMock::perform_scattered_io(IOVecs buffers[], Baddrs *dev_offsets, bool is_write, Future *io_future)
{
    PANIC("UNIMPLEMENTED!");
    return true;
}

}
}
