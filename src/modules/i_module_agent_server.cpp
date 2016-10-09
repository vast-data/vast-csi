#include "i_module_agent_server.hpp"
#include "i_module.hpp"

void IModuleAgentServerImpl::init(P::SiloId silo_id, IModule *module)
{
    _module = module;
    register_server(silo_id, ModuleId::I);
}

void IModuleAgentServerImpl::activate(P::VProto::Empty::RootReader *args, P::VProto::Empty::RootBuilder *result)
{
    _module->activate();
}

void IModuleAgentServerImpl::create_estore(P::VProto::Empty::RootReader *args, P::VProto::Empty::RootBuilder *result)
{
    _module->create_estore();
}
