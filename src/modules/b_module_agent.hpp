/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "control/agent.hpp"

class BModuleAgent : public Control::BaseAgent {
public:
    void init(P::SiloId silo_id, ModuleId module_id) {
        Control::BaseAgent::init(silo_id, module_id, FiberGroupId::B);
    }

private:
};  // class BModuleAgent
