#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "modules/e_module.vproto.hpp"
#include "modules/e_module_agent.rpc.server.hpp"

namespace P {

class EModuleAgentServerImpl : public EModuleAgentServer {
public:
    void init(SiloId silo_id, ModuleId module_id) { register_server(silo_id, module_id); }

private:
    void connect(ConnectParams::RootReader *args, uint16_t request_len,
                 VProto::Empty::RootBuilder *res, uint16_t *reply_len);
    void disconnect(DisconnectParams::RootReader *args, uint16_t request_len,
                    VProto::Empty::RootBuilder *res, uint16_t *reply_len);
};  // class EModuleAgentServerImpl

}  // namespace P
