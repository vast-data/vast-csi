#include <p.h>
#include "defs.h"

#define DEFINE_LOOKUP_STRING(x) #x
#define DEFINE_LOOKUP_IMPLEMENTATION(list, name, array, id_to_string, string_to_id) \
    static const char *array[] = {                                      \
        list(DEFINE_LOOKUP_STRING),                                     \
        NULL                                                            \
    };                                                                  \
    const char *id_to_string(name id)                                   \
    {                                                                   \
        return array[id];                                               \
    }                                                                   \
    name string_to_id(const char *string)                               \
    {                                                                   \
        for (name i = 0; array[i] != NULL; i++)                         \
            if (strcmp(array[i], string) == 0)                          \
                return i;                                               \
        P_PANIC();                                                      \
    }

DEFINE_LOOKUP_IMPLEMENTATION(MODULE_LIST, ModuleId, module_id_strings,
                             module_id_to_string, string_to_module_id)
DEFINE_LOOKUP_IMPLEMENTATION(COMPONENT_LIST, ComponentId, component_id_strings,
                             component_id_to_string, string_to_component_id)
DEFINE_LOOKUP_IMPLEMENTATION(FIBER_GROUP_LIST, FiberGroupId, fiber_group_id_strings,
                             fiber_group_id_to_string, string_to_fiber_group_id)

#include "modules/p_module.h"
#include "modules/i_module.h"

void *(*module_init_functions[])(PSilo *silo, PConfigSetting *setting) = {
    p_module_init,
    i_module_init
};

void (*module_start_functions[])(void) = {
    p_module_start,
    i_module_start
};
