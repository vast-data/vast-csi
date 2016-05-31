#include <p.h>
#include "p_module.h"

#define CURRENT_COMPONENT COMPONENT_PLASMA

typedef struct PModuleState PModuleState;
struct PModuleState {
    PIOProvider *io_provider;
    char foo;
};

void *p_module_init(PSilo *silo, PConfigSetting *module_setting)
{
    PModuleState *state = p_safe_malloc(sizeof(PModuleState));

    PConfigSetting *io_module_setting = p_config_setting_lookup_required(module_setting, "io_module");
    state->io_provider = p_io_provider_init_from_settings(io_module_setting);

    state->foo = 'a';

    p_silo_set_component_state(silo, MODULE_P, CURRENT_COMPONENT, state);
    return state;
}

static void NO_RETURN p_io_poll_fiber()
{
    PModuleState *module_state = p_get_module_state();
    while (true) {
        p_io_provider_poll(module_state->io_provider);
        p_fiber_yield();
    }
}

void p_module_start()
{
    PModuleState *module_state = p_get_module_state();
    P_ASSERT(module_state->foo == 'a');
    P_ASSERT(COMPONENT_GET_STATE() == module_state);

    p_fiber_init(FIBER_GROUP_P_IO_POLLING, p_io_poll_fiber, NULL, false);
}
