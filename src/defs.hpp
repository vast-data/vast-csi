/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.hpp
 * \brief Identifiers for various parts of software (fiber groups, components, etc')
 */
#pragma once

#include "plasma/utils/macros.hpp"

namespace P {

static const uint16_t MAX_ENVS = 32;

}

#define COMPONENT_LIST(X)                       \
    X(PLASMA),                                  \
    X(NFS),                                     \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(COMPONENT_LIST,
                         ComponentId,
                         component_id_to_string,
                         component_id_from_string)

#define FIBER_GROUP_LIST(X)                  \
    X(E),                                    \
    X(E_IO_POLLING),                         \
    X(E_VMSG_POLLING),                       \
    X(P),                                    \
    X(NFS_POLLING),                          \
    X(PROTO),                                \
    X(TEST),                                 \
    X(I_TEST),                               \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(FIBER_GROUP_LIST,
                         FiberGroupId,
                         fiber_group_id_to_string,
                         fiber_group_id_from_string)

#define MODULES_LIST(X) \
    X(P),               \
    X(E),               \
    X(I),               \
    X(TEST),            \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(MODULES_LIST,
                         ModuleId,
                         module_id_to_string,
                         module_id_from_string)

static const uint8_t MODULES_COUNT = (uint8_t)ModuleId::COUNT;
// messaging uses only 4 bits for module id, if we need more than 16 modules the messaging code must be updated
static_assert(MODULES_COUNT <= 16, "the max number of supported modules is 16");
