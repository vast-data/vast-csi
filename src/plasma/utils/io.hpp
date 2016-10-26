/* Copyright (C) Vast Data Ltd. */
/*!
 * \file io.hpp
 * \brief IO related definitions
 */

#pragma once

#include <sys/uio.h>
#include "types.hpp"

namespace P {

namespace IO {

typedef struct iovec IOVec;
class IOVecs {
public:
    uint32_t count;
    IOVec *iovecs;

    size_t total_length() const
    {
        size_t ret = 0;
        for (uint32_t i = 0; i < count; ++i) {
            ret += iovecs[i].iov_len;
        }
        return ret;
    }

    void trace();
};

typedef uint64_t Baddr;

}
}
