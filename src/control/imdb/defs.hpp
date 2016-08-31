/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.hpp
 * \brief System objects definitions.
 */
#pragma once

#include "plasma/utils/types.hpp"
#include "system.hpp"
#include "cnode.hpp"
#include "drive.hpp"

namespace Control {

struct TypeConfig {
    P::Index object_size;
    P::Index max_objects;
};

// this array should be coordinated with the TypeId enum in object.hpp
TypeConfig type_configs[(P::byte)TypeId::COUNT] = {{sizeof(System), 64}, {sizeof(CNode), 2048}, {sizeof(Drive), 4096}};

}
