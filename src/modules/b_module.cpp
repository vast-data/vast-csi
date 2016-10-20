#include "b_module.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/internal.hpp"
#include "globals.hpp"

using namespace P::Conf;

void BModule::init(P::Silo *silo, ConfigSetting *module_setting)
{
    ConfigSetting *lock_manager_setting = conf_setting_lookup_required(module_setting, "components.lock_manager");
    _agent.init(silo->get_id(), get_id());
    _lock_manager_server.init(silo->get_id(), ModuleId::B, lock_manager_setting);
}

void BModule::start()
{
}

/* static */ void BModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 10, "B");
}

/* static */ void BModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    get_default_vmsg_module_resources(vmsg_module_resources);
    vmsg_module_resources->num_rdma_buffers = 1;
    vmsg_module_resources->size_rdma_buffers = P::DNODE_RDMA_BUFFER_SIZE;
}
