/* Copyright (C) Vast Data Ltd. */

/*!
 * \file agent.hpp
 * \brief The control agent.
 */
#pragma once

#include "plasma/metrics/agent.hpp"
#include "plasma/metrics/agent_rpc_server.hpp"
#include "plasma/execution/silo.hpp"

namespace P { namespace Control {

class Agent {
public:
    void init(SiloId silo_id, ModuleId module_id) {
        metrics_agent.init();
        metrics_server.register_server(silo_id, module_id);
    }

    Metrics::Agent metrics_agent;
    Metrics::MetricsAgentServerImpl metrics_server;
};

}}
