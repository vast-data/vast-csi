#include <p.h>
#include "p_module.h"

#define CURRENT_COMPONENT COMPONENT_PLASMA

typedef struct PModuleState PModuleState;
struct PModuleState {
    char foo;
};

void *p_module_init(PSilo *silo)
{
    PModuleState *state = p_safe_malloc(sizeof(PModuleState));
    state->foo = 'a';
    p_silo_set_component_state(silo, MODULE_P, CURRENT_COMPONENT, state);
    printf("P init\n");
    return state;
}

void p_module_start()
{
    PModuleState *module_state = p_get_module_state();
    P_ASSERT(module_state->foo == 'a');
    P_ASSERT(COMPONENT_GET_STATE() == module_state);
    printf("P start\n");
}
