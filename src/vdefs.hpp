/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.hpp
 * \brief Identifiers for various parts of software (modules, components, etc')
 */
#pragma once

#include "plasma/utils/macros.hpp"

#define MODULE_LIST(X)                          \
    X(P),                                       \
    X(I),                                       \
    X(TEST),                                    \
    X(COUNT)


// TODO get rid of the  "_CPP" once the c code is gone
DEFINE_LOOKUP_PROTOTYPES_CPP(MODULE_LIST,
                         ModuleId, // the name of the enum
                         module_id_to_string, // the function that converts id to string
                         module_id_from_string) // the function that converts string to id

#define COMPONENT_LIST(X)                       \
    X(PLASMA),                                  \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES_CPP(COMPONENT_LIST,
                         ComponentId,
                         component_id_to_string,
                         component_id_from_string)

#define FIBER_GROUP_LIST(X)                  \
    X(P),                                    \
    X(P_IO_POLLING),                         \
    X(TEST),                                 \
    X(I_TEST),                               \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES_CPP(FIBER_GROUP_LIST,
                         FiberGroupId,
                         fiber_group_id_to_string,
                         fiber_group_id_from_string)

// forward declarations
namespace P {
    class Silo;
}
typedef struct config_setting_t ConfigSetting;

extern void *(*module_init_functions[])(P::Silo *silo, ConfigSetting *setting);
extern void (*module_start_functions[])(void);
