#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "modules/e_module.vproto.hpp"
#include "modules/e_module_agent.rpc.server.hpp"

namespace P {

class EModuleAgentServerImpl : public EModuleAgentServer {
public:
    void init(SiloId silo_id, ModuleId module_id) { register_server(silo_id, module_id); }

    static void do_connect(ConnectParams::Reader *args);

private:
    void connect(ConnectParams::RootReader *args, VProto::Empty::RootBuilder *res);
    void disconnect(DisconnectParams::RootReader *args, VProto::Empty::RootBuilder *res);
    void vmsg_ping(VProto::Empty::RootReader *args, VProto::Empty::RootBuilder *res);
};  // class EModuleAgentServerImpl

}  // namespace P
