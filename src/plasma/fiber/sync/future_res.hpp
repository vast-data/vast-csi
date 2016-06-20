/* Copyright (C) Vast Data Ltd. */

/*!
 * \file future_res.hpp
 * \brief An future object for cross-fiber coordination
 */
#pragma once

#include "future.hpp"

namespace P {

namespace FiberSync {

template < typename T >
class FutureRes : public Future {
public:
    // First attempt had a setter and getter but it was too limiting
    // for use cases of referencing a large object in pool for instance.
    // This is far from safe but allows maximum flexibility and minimum copies.
    T res;
};

}
}
