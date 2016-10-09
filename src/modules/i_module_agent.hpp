/* Copyright (C) Vast Data Ltd. */
#pragma once

#include "i_module_agent_server.hpp"
#include "control/agent.hpp"

class IModuleAgent : public Control::BaseAgent {
public:
    void init(P::SiloId silo_id, IModule *module) {
        Control::BaseAgent::init(silo_id, ModuleId::I, FiberGroupId::I_CONTROL);
        _rpc_server.init(silo_id, module);
    }

private:
    IModuleAgentServerImpl _rpc_server;
};
