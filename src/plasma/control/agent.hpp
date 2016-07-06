/* Copyright (C) Vast Data Ltd. */

/*!
 * \file agent.hpp
 * \brief The control agent.
 */
#pragma once

#include "plasma/metrics/agent.hpp"

namespace P { namespace Control {

class Agent {
public:
    void init() {
        metrics_agent.init();
    }

    Metrics::Agent metrics_agent;
};

}}
