#include "e_module_agent_server.hpp"
#include "plasma/execution/env.hpp"

namespace P {

void EModuleAgentServerImpl::connect(ConnectParams::RootReader *args, uint16_t request_len,
                                     VProto::Empty::RootBuilder *res, uint16_t *reply_len)
{
    VMsg::EnvAddresses::Reader addresses_reader;
    args->get_addresses(&addresses_reader);
    VMsg::EnvAddresses::RootBuilder addresses;
    addresses.init_from_reader(&addresses_reader);
    Env::get()->get_vmsg()->set_env_addresses(args->get_env_id(), &addresses);
    *reply_len = sizeof(VProto::Empty);
}

void EModuleAgentServerImpl::disconnect(DisconnectParams::RootReader *args, uint16_t request_len,
                                        VProto::Empty::RootBuilder *res, uint16_t *reply_len)
{
    PANIC("not implemented");  // TODO: implement once vmsg supports "disconnect".
}

}  // namespace P
