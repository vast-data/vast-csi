/* Copyright (C) Vast Data Ltd. */

/*!
 * \file agent.hpp
 * \brief The control agent.
 */
#pragma once

#include "plasma/metrics/agent.hpp"
#include "plasma/execution/silo.hpp"

namespace Control {

class BaseAgent {
public:
    void init(P::SiloId silo_id, ModuleId module_id, FiberGroupId metrics_fiber_group_id) {
        _is_initialized = true;
        _metrics_agent.init(silo_id, module_id, metrics_fiber_group_id);
    }

    P::Metrics::MetricsAgent* get_metrics_agent() { return &_metrics_agent; }

    bool is_initialized() { return _is_initialized; }

private:
    P::Metrics::MetricsAgent _metrics_agent;
    bool _is_initialized = false;  // Used by the silo to verify all module agents call Agent::init().
};

}
