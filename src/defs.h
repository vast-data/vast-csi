/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.h
 * \brief Identifiers for various parts of software (modules, components, etc')
 */
#pragma once

#include "plasma/macro.h"

#define MODULE_LIST(X)                                 \
    X(MODULE_P),                                       \
    X(MODULE_I),                                       \
    X(MODULE_COUNT)

DEFINE_LOOKUP_PROTOTYPES(MODULE_LIST,
                         ModuleId, // the name of the enum
                         module_id_to_string, // the function that converts id to string
                         module_id_from_string) // the function that converts string to id

#define COMPONENT_LIST(X)                       \
    X(COMPONENT_PLASMA),                        \
    X(COMPONENT_COUNT)

DEFINE_LOOKUP_PROTOTYPES(COMPONENT_LIST,
                         ComponentId,
                         component_id_to_string,
                         component_id_from_string)

#define FIBER_GROUP_LIST(X)                              \
    X(FIBER_GROUP_P),                                    \
    X(FIBER_GROUP_P_IO_POLLING),                         \
    X(FIBER_GROUP_I_TEST),                               \
    X(FIBER_GROUP_COUNT)

DEFINE_LOOKUP_PROTOTYPES(FIBER_GROUP_LIST,
                         FiberGroupId,
                         fiber_group_id_to_string,
                         fiber_group_id_from_string)

typedef struct PSilo PSilo;
typedef struct config_setting_t PConfigSetting;
extern void *(*module_init_functions[])(PSilo *silo, PConfigSetting *setting);
extern void (*module_start_functions[])(void);
