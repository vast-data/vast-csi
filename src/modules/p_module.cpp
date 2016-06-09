#include "p_module.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/internal.hpp"

using namespace P::Conf;
using P::Silo;

typedef struct PModuleState PModuleState;
struct PModuleState {
    P::IOProvider io_provider;
    P::AtomicPool<P::DevIO::IO> iopool;
    P::DevIO *devices;
    char foo;
};

void PModule::init_io_from_settings(ConfigSetting *io_module, P::DevIO **devices, P::AtomicPool<P::DevIO::IO> *iopool, P::IOProvider *io_provider)
{
    ConfigSetting* iopool_count_setting = conf_setting_lookup_required(io_module, "io_pool_count");
    size_t iopool_count = conf_setting_get_int32(iopool_count_setting);
    iopool->init(iopool_count);

    ConfigSetting *io_provider_setting = conf_setting_lookup_required(io_module, "io_provider");
    ConfigSetting *devices_setting = conf_setting_lookup_required(io_provider_setting, "devices");
    const size_t device_count = (size_t)conf_setting_length(devices_setting);
    *devices = new P::DevIO[device_count];

    LOOP(device_count, i)
    {
        ConfigSetting *device_setting = conf_setting_get_element(devices_setting, (uint32_t) i);
        ConfigSetting *dev_path_setting = conf_setting_lookup_required(device_setting, "dev_path");
        ConfigSetting *io_depth_setting = conf_setting_lookup_required(device_setting, "io_depth");
        ConfigSetting *device_size_setting = conf_setting_lookup_required(device_setting, "device_size");

        if (unlikely(!(*devices)[i].init(conf_setting_get_string(dev_path_setting),
                                      (uint32_t)conf_setting_get_int32(io_depth_setting), iopool,
                                      (size_t)conf_setting_get_int32(device_size_setting)))) {
            // Todo: this should be replaces with a notification to control and then possibly skip/retry/panic?
            PANIC();
        }
    }

    io_provider->init(*devices, device_count);
}

void *PModule::init(Silo *silo, ConfigSetting *module_setting)
{
    PModuleState *state = new PModuleState;

    ConfigSetting *io_module_setting = conf_setting_lookup_required(module_setting, "io_module");
    init_io_from_settings(io_module_setting, &state->devices, &state->iopool, &state->io_provider);

    state->foo = 'a';
    silo->set_component_state(ModuleId::P, CURRENT_COMPONENT, state);
    return state;
}

static void NO_RETURN p_io_poll_fiber(void *)
{
    PModuleState *module_state = (PModuleState *)Silo::get_module_state();
    while (true) {
        module_state->io_provider.poll();
        P::Fiber::yield();
    }
}

void PModule::start()
{
    printf("PModule::start\n");
    PModuleState *module_state = (PModuleState *)Silo::get_module_state();
    ASSERT_EQUAL(module_state->foo, 'a');
    ASSERT_EQUAL(COMPONENT_GET_STATE(), module_state);
    P::Fiber::init((P::Index)FiberGroupId::P_IO_POLLING, p_io_poll_fiber, nullptr, false);
}
