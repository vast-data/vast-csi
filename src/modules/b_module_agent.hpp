#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/control/agent.hpp"

class BModuleAgent : public P::Control::Agent {
public:
    void init(P::SiloId silo_id, ModuleId module_id) {
        P::Control::Agent::init(silo_id, module_id, FiberGroupId::B);
    }

private:
};  // class BModuleAgent

