#include "e_module_agent_server.hpp"
#include "plasma/execution/env.hpp"

#define CURRENT_COMPONENT ComponentId::PLASMA

namespace P {

/* static */ void EModuleAgentServerImpl::do_connect(ConnectParams::Reader *args)
{
    VMsg::EnvAddresses::Reader addresses_reader;
    args->get_addresses(&addresses_reader);
    VMsg::EnvAddresses::RootBuilder addresses;
    addresses.init_from_reader(&addresses_reader);
    Env::get()->get_vmsg()->set_env_addresses(args->get_env_id(), &addresses);
}

void EModuleAgentServerImpl::connect(ConnectParams::RootReader *args, VProto::Empty::RootBuilder *res)
{
    ConnectParams::Reader connect_params;
    connect_params.init_from_root(args);
    do_connect(&connect_params);
}

void EModuleAgentServerImpl::disconnect(DisconnectParams::RootReader *args, VProto::Empty::RootBuilder *res)
{
    PANIC("not implemented");  // TODO: implement once vmsg supports "disconnect".
}

void EModuleAgentServerImpl::vmsg_ping(VProto::Empty::RootReader *args, VProto::Empty::RootBuilder *res)
{
#ifdef DEBUG
    PT_DEBUG(DATA, "PING!");
#endif
}

}  // namespace P
