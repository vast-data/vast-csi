/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.hpp
 * \brief Identifiers for various parts of software (fiber groups, components, etc')
 */
#pragma once

#include "plasma/utils/macros.hpp"

namespace P {

static const uint16_t MAX_ENVS_PER_CNODE = 4;
static const uint16_t MAX_CNODES_PER_SYSTEM = 1024;
static const uint16_t MAX_ENVS_PER_SYSTEM = MAX_CNODES_PER_SYSTEM * MAX_ENVS_PER_CNODE;

static const char *LOCALHOST = "127.0.0.1";
static const uint16_t PLATFORM_ENV_PORT = 4000;
static const uint16_t PLATFORM_ENV_INITIAL_ID = 0;
static const uint16_t LEADER_ENV_ID = 1;
static const uint8_t DNODE_NVRAM_COUNT = 2;

static const char LEADER_ENV_GUID[] = "12345678-9abc-def1-aaaa-bbbbccccdddd";

}

// update src/plasma/trace/reader/tracereader/ui.py:~34
#define COMPONENT_LIST(X)                       \
    X(TEST),                                    \
    X(PLASMA),                                  \
    X(NFS),                                     \
    X(CLUSTER),                                 \
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
    X(C),                                    \
    X(B),                                    \
    X(I_NFS_POLLING),                        \
    X(I_PROTO),                              \
    X(I_CONTROL),                            \
    X(TEST),                                 \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(FIBER_GROUP_LIST,
                         FiberGroupId,
                         fiber_group_id_to_string,
                         fiber_group_id_from_string)

#define MODULES_LIST(X) \
    X(P),               \
    X(E),               \
    X(C),               \
    X(I),               \
    X(B),               \
    X(TEST),            \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(MODULES_LIST,
                         ModuleId,
                         module_id_to_string,
                         module_id_from_string)

static const uint8_t MODULES_COUNT = (uint8_t)ModuleId::COUNT;
// messaging uses only 4 bits for module id, if we need more than 16 modules the messaging code must be updated
static_assert(MODULES_COUNT <= 16, "the max number of supported modules is 16");
