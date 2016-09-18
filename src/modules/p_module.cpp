#include "p_module.hpp"
#include "plasma/vmsg/vmsg.hpp"
#include "plasma/execution/env.hpp"

namespace P {

void PModule::init(Silo *silo, Conf::ConfigSetting *module_setting)
{
    _agent.init(silo->get_id(), get_id());

    // TODO: these calls should be removed - see ticket ORION-65
    Env::get()->get_vmsg()->add_module_pair(ModuleId::TEST, ModuleId::P, VMsg::TransportType::RDMA);
    Env::get()->get_vmsg()->add_module_pair(ModuleId::C, ModuleId::P, VMsg::TransportType::RDMA);
}

}  // namespace P
