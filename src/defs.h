/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.h
 * \brief Identifiers for various parts of software (modules, components, etc')
 */
#pragma once

/*!
 * The following macros provide a template for creating an enum
 * Along with helper functions that convert between enum values and strings.
 */

#define DEFINE_LOOKUP_ID(x) x
#define DEFINE_LOOKUP_PROTOTYPES(list, name, array, id_to_string, string_to_id) \
    typedef enum {                                                      \
        list(DEFINE_LOOKUP_ID)                                          \
    } name;                                                             \
    const char *id_to_string(name id);                                  \
    name string_to_id(const char *string);

#define MODULE_LIST(X)                                 \
    X(MODULE_P),                                       \
    X(MODULE_I),                                       \
    X(MODULE_COUNT)

DEFINE_LOOKUP_PROTOTYPES(MODULE_LIST,
                         ModuleId, // the name of the enum
                         module_id_strings, // the name of the static array
                         module_id_to_string, // the function that converts id to string
                         string_to_module_id) // the function that converts string to id

#define COMPONENT_LIST(X)                       \
    X(COMPONENT_PLASMA),                        \
    X(COMPONENT_COUNT)

DEFINE_LOOKUP_PROTOTYPES(COMPONENT_LIST,
                         ComponentId,
                         component_id_strings,
                         component_id_to_string,
                         string_to_component_id)

#define FIBER_GROUP_LIST(X)                       \
    X(FIBER_GROUP_P),                       \
    X(FIBER_GROUP_P_IO_POLLING),                         \
    X(FIBER_GROUP_I_START),                       \
    X(FIBER_GROUP_COUNT)

DEFINE_LOOKUP_PROTOTYPES(FIBER_GROUP_LIST,
                         FiberGroupId,
                         fiber_group_id_strings,
                         fiber_group_id_to_string,
                         string_to_fiber_group_id)

typedef struct PSilo PSilo;
typedef struct config_setting_t PConfigSetting;
extern void *(*module_init_functions[])(PSilo *silo, PConfigSetting *setting);
extern void (*module_start_functions[])(void);
