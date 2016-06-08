#include "vdefs.hpp"

DEFINE_LOOKUP_IMPLEMENTATION_CPP(COMPONENT_LIST, ComponentId, component_id_strings,
                             component_id_to_string, component_id_from_string)
DEFINE_LOOKUP_IMPLEMENTATION_CPP(FIBER_GROUP_LIST, FiberGroupId, fiber_group_id_strings,
                             fiber_group_id_to_string, fiber_group_id_from_string)
