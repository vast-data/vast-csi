#include <p.h>
#include "defs.h"

DEFINE_LOOKUP_IMPLEMENTATION(MODULE_LIST, ModuleId, module_id_strings,
                             module_id_to_string, module_id_from_string)
DEFINE_LOOKUP_IMPLEMENTATION(COMPONENT_LIST, ComponentId, component_id_strings,
                             component_id_to_string, component_id_from_string)
DEFINE_LOOKUP_IMPLEMENTATION(FIBER_GROUP_LIST, FiberGroupId, fiber_group_id_strings,
                             fiber_group_id_to_string, fiber_group_id_from_string)

