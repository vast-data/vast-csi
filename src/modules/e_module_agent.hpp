#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "e_module_agent_server.hpp"
#include "plasma/control/agent.hpp"

namespace P {

class EModuleAgent : public Control::Agent {
public:
    void init(SiloId silo_id, ModuleId module_id) {
        Control::Agent::init(silo_id, module_id);

        // Env-related functionality should run only on the first silo.
        if (Silo::get_current_silo_id() == 0) {
            _rpc_server.init(silo_id, module_id);
        }
    }

private:
    EModuleAgentServerImpl _rpc_server;
};  // class EModuleAgent

};  // namespace P
