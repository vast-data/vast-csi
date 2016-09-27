#include <plasma/vmsg/vmsg_defs.hpp>
#include "e_module_agent_server.hpp"
#include "plasma/execution/env.hpp"

#define CURRENT_COMPONENT ComponentId::PLASMA

static_assert(P::MODULES_COUNT == ::MODULES_COUNT, "MODULES_COUNT in e_module.vproto must be the same as MODULES_COUNT");

namespace P {

/* static */ void EModuleAgentServerImpl::do_connect(ConnectParams::Reader *args)
{
    VMsg::EnvAddresses::Reader addresses_reader;
    args->get_addresses(&addresses_reader);
    VMsg::EnvAddresses::RootBuilder addresses;
    addresses.init_from_reader(&addresses_reader);

    ASSERT_EQUAL(MODULES_COUNT, args->get_modules_count());
    EnvModules env_modules= { 0 };
    LOOP(MODULES_COUNT, i)
    {
        env_modules.env_modules[i] = *args->get_modules(i);
    }
    Env::get()->get_vmsg()->set_env_addresses(args->get_env_id(), &addresses, &env_modules);
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
