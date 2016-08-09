#include <stdint.h>

#/* Copyright (C) Vast Data Ltd. */
/*!
 * \file io.hpp
 * \brief IO related definitions
 */

#pragma once

#include <sys/uio.h>

namespace P {

typedef struct iovec IOVec;
struct IOVecs {
    uint32_t count;
    IOVec *iovecs;
};

}
