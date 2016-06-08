#include "p_module.hpp"
#include "plasma/io/p_io_provider_private.h"
#include "plasma/io/p_io_provider.h"
#include "plasma/fiber/p_fiber.h"

using namespace P::Conf;
using P::Silo;

#define CURRENT_COMPONENT ComponentId::PLASMA

typedef struct PModuleState PModuleState;
struct PModuleState {
    PIOProvider *io_provider;
    char foo;
};

void *PModule::init(Silo *silo, ConfigSetting *module_setting)
{
    PModuleState *state = new PModuleState;

    PConfigSetting *io_module_setting = conf_setting_lookup_required(module_setting, "io_module");
    state->io_provider = p_io_provider_init_from_settings(io_module_setting);

    state->foo = 'a';
    silo->set_component_state(ModuleId::P, CURRENT_COMPONENT, state);
    return state;
}

static void NO_RETURN p_io_poll_fiber(void *)
{
    PModuleState *module_state = (PModuleState *)Silo::get_module_state();
    while (true) {
        p_io_provider_poll(module_state->io_provider);
        p_fiber_yield();
    }
}

void PModule::start()
{
    printf("PModule::start\n");
    PModuleState *module_state = (PModuleState *)Silo::get_module_state();
    ASSERT_EQUAL(module_state->foo, 'a');
    ASSERT_EQUAL(COMPONENT_GET_STATE(), module_state);
    P::Fiber::init((PIndex)FiberGroupId::P_IO_POLLING, p_io_poll_fiber, NULL, false);
}
