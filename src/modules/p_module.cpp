#include "p_module.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/internal.hpp"
#include "globals.hpp"

using namespace P::Conf;
using P::Silo;
using P::VMsg::VMsg;

void PModule::init_io_from_settings(ConfigSetting *io_setting, P::DevIO **devices, P::AtomicPool<P::DevIO::IO> *iopool, P::IOProvider *io_provider)
{
    ConfigSetting* iopool_count_setting = conf_setting_lookup_required(io_setting, "io_pool_count");
    size_t iopool_count = conf_setting_get_int32(iopool_count_setting);
    iopool->init(iopool_count);

    ConfigSetting *io_provider_setting = conf_setting_lookup_required(io_setting, "io_provider");
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
            // TODO: this should be replaces with a notification to control and then possibly skip/retry/panic?
            PANIC();
        }
    }

    io_provider->init(*devices, device_count);
}

void PModule::init(Silo *silo, ConfigSetting *module_setting)
{
    ConfigSetting *io_setting = conf_setting_lookup_required(module_setting, "io");
    init_io_from_settings(io_setting, &devices, &iopool, &io_provider);
}

static void io_poll_fiber(void *module)
{
    PModule *p_module = (PModule *) module;
    while (true) {
        p_module->io_provider.poll();
        P::Fiber::yield();
        if (unlikely(env_stop)) {
            break;
        }
    }
}

static void vmsg_poll_fiber(void *module)
{
    VMsg *vmsg = P::Env::get()->get_vmsg();
    while (true) {
        vmsg->poll();
        P::Fiber::yield();
        if (unlikely(env_stop)) {
            break;
        }
    }
}

void PModule::start()
{
    P::Fiber::init((P::Index)FiberGroupId::P_IO_POLLING, io_poll_fiber, this, false);
    P::Fiber::init((P::Index)FiberGroupId::P_VMSG_POLLING, vmsg_poll_fiber, this, false);
}
