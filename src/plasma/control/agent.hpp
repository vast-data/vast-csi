/* Copyright (C) Vast Data Ltd. */

/*!
 * \file agent.hpp
 * \brief The control agent.
 */
#pragma once

#include "plasma/metrics/agent.hpp"
#include "plasma/execution/silo.hpp"

namespace P { namespace Control {

class Agent {
public:
    void init(SiloId silo_id, ModuleId module_id) {
        metrics_agent.init(silo_id, module_id);
    }

    Metrics::MetricsAgent metrics_agent;
};

}}
