/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "p_module_agent_server.hpp"
#include "control/agent.hpp"

namespace P {

class PModuleAgent : public Control::BaseAgent {
public:
    void init(SiloId silo_id, ModuleId module_id, Conf::ConfigSetting *module_setting) {
        Control::BaseAgent::init(silo_id, module_id, FiberGroupId::P);
        _rpc_server.init(silo_id, module_id, module_setting);
    }

private:
    PModuleAgentServerImpl _rpc_server;
};  // class PModuleAgent

};  // namespace P
