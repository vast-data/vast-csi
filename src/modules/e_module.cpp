#include "e_module.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/internal.hpp"
#include "globals.hpp"

namespace P {

/* static */ void EModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 50, "E");
    add_fiber_group_config(module_config, 1, "E_VMSG_POLLING");
}

/* static */ void EModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
}

void EModule::init(Silo *silo, Conf::ConfigSetting *setting)
{
    _agent.init(silo->get_id(), get_id());
}

void EModule::start()
{
    Env::get()->get_vmsg()->start_silo_fiber();
}

}  // namespace P
