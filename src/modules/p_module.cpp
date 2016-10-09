#include "p_module.hpp"
#include "plasma/vmsg/vmsg.hpp"
#include "plasma/execution/env.hpp"

namespace P {

void PModule::init(Silo *silo, Conf::ConfigSetting *module_setting)
{
    _agent.init(silo->get_id(), get_id(), module_setting);
}

/* static */ void PModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 10, "P");
}

/* static */ void PModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
}

}  // namespace P
