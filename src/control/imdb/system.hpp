/* Copyright (C) Vast Data Ltd. */

/*!
 * \file system.hpp
 * \brief System object implementation.
 */
#pragma once

#include <limits>
#include "system.vproto.hpp"
#include "object.hpp"

namespace Control {

class System : public Object<SystemProto, TypeId::System> {
public:
    uint16_t allocate_env_id()
    {
        uint16_t result = get_next_env_id();
        ASSERT(result != std::numeric_limits<uint16_t>::max(), "Env id overflow!");
        set_next_env_id(result + 1);
        return result;
    }

    uint16_t allocate_cnode_id()
    {
        uint16_t result = get_next_cnode_id();
        ASSERT(result != std::numeric_limits<uint16_t>::max(), "CNode id overflow!");
        set_next_cnode_id(result + 1);
        return result;
    }

    uint16_t allocate_dbox_id()
    {
        uint16_t result = get_next_dbox_id();
        ASSERT(result != std::numeric_limits<uint16_t>::max(), "DBox id overflow!");
        set_next_dbox_id(result + 1);
        return result;
    }

    uint16_t allocate_dnode_id()
    {
        uint16_t result = get_next_dnode_id();
        ASSERT(result != std::numeric_limits<uint16_t>::max(), "DNode id overflow!");
        set_next_dnode_id(result + 1);
        return result;
    }
};

}
