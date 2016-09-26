/* Copyright (C) Vast Data Ltd. */

/*!
 * \file system.hpp
 * \brief System object implementation.
 */
#pragma once

#include <limits>
#include "system.vproto.hpp"
#include "object.hpp"

#define ID_ALLOCATOR_METHOD(counter)                                    \
    uint16_t allocate_##counter()                                       \
    {                                                                   \
        uint16_t result = get_next_##counter();                         \
        ASSERT(result != std::numeric_limits<uint16_t>::max(), #counter " overflow!"); \
        set_next_##counter(result + 1);                                 \
        return result;                                                  \
    }

namespace Control {

class System : public Object<SystemProto, TypeId::System> {

public:
    ID_ALLOCATOR_METHOD(env_id)
    ID_ALLOCATOR_METHOD(cnode_id)
    ID_ALLOCATOR_METHOD(dbox_id)
    ID_ALLOCATOR_METHOD(dnode_id)
};

}
