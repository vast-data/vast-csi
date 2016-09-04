/* Copyright (C) Vast Data Ltd. */

/*!
 * \file mem_io.hpp
 * \brief memory IO interface
 *
 * Extends basic IO operations to support RDMA specific operations such as atomic operations.
 *
 */

#pragma once

#include "base_io.hpp"

namespace P {

namespace IO {

class MemIO : public BaseIO {

public:
    virtual WARN_UNUSED bool compare_and_swap(Baddr address, uint64_t new_val, uint64_t exp_val, uint64_t* old_val OUT) = 0;
};

}
}
