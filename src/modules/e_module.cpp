#include "e_module.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/internal.hpp"
#include "globals.hpp"

namespace P {

using Conf::ConfigSetting;

namespace {

static constexpr int32_t IO_POOL_COUNT = 100;

}  // namespace

/* static */ void EModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: put this (io) under "components".
    ConfigSetting *io = P::Conf::conf_setting_add_group(module_config, "io");
    P::Conf::ConfigSetting *io_pool_count = P::Conf::conf_setting_add(io, "io_pool_count", CONFIG_TYPE_INT32);
    P::Conf::conf_setting_set_int32(io_pool_count, IO_POOL_COUNT);
    P::Conf::ConfigSetting *io_provider = P::Conf::conf_setting_add_group(io, "io_provider");
    P::Conf::ConfigSetting *devices = P::Conf::conf_setting_add(io_provider, "devices", CONFIG_TYPE_LIST);

    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 50, "E");
    add_fiber_group_config(module_config, 1, "E_IO_POLLING");
    add_fiber_group_config(module_config, 1, "E_VMSG_POLLING");
}

/* static */ void EModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
}

/* static */ void EModule::init_io_from_settings(ConfigSetting *io_setting, DevIO **devices,
                                                 AtomicPool<DevIO::IO> *iopool, IOProvider *io_provider)
{
    ConfigSetting *iopool_count_setting = Conf::conf_setting_lookup_required(io_setting, "io_pool_count");
    size_t iopool_count = Conf::conf_setting_get_int32(iopool_count_setting);
    iopool->init(iopool_count);

    ConfigSetting *io_provider_setting = Conf::conf_setting_lookup_required(io_setting, "io_provider");
    ConfigSetting *devices_setting = Conf::conf_setting_lookup_required(io_provider_setting, "devices");
    const size_t device_count = (size_t)Conf::conf_setting_length(devices_setting);
    *devices = new DevIO[device_count];

    LOOP(device_count, i) {
        ConfigSetting *device_setting = Conf::conf_setting_get_element(devices_setting, (uint32_t) i);
        ConfigSetting *dev_path_setting = Conf::conf_setting_lookup_required(device_setting, "dev_path");
        ConfigSetting *io_depth_setting = Conf::conf_setting_lookup_required(device_setting, "io_depth");
        ConfigSetting *device_size_setting = Conf::conf_setting_lookup_required(device_setting, "device_size");

        if (unlikely(!(*devices)[i].init(Conf::conf_setting_get_string(dev_path_setting),
                                         (uint32_t) Conf::conf_setting_get_int32(io_depth_setting), iopool,
                                         (size_t) Conf::conf_setting_get_int32(device_size_setting)))) {
            // TODO: this should be replaced with a notification to control and then possibly skip/retry/panic?
            PANIC();
        }
    }

    io_provider->init(*devices, device_count);
}

void EModule::init(Silo *silo, ConfigSetting *module_setting)
{
    ConfigSetting *io_setting = Conf::conf_setting_lookup_required(module_setting, "io");
    init_io_from_settings(io_setting, &devices, &iopool, &io_provider);
    _agent.init(silo->get_id(), get_id());
}

void EModule::start()
{
    io_provider.start();
    Env::get()->get_vmsg()->start_silo_fiber();
}

}  // namespace P
