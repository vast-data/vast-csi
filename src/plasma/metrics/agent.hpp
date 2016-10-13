/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "metrics_agent.rpc.server.hpp"
#include "tracker.hpp"

namespace P { namespace Metrics {

class MetricsAgent : public MetricsAgentServer {
public:
    void init(SiloId silo_id, ModuleId module_id, FiberGroupId fiber_group_id)
    {
        tracker.init();
        register_server(silo_id, module_id, fiber_group_id);
    }

    Metrics::Tracker tracker;

private:
    void get_generations(Metrics::GetGenerationsParams::RootReader *args, Metrics::GetGenerationsResult::RootBuilder *res);
    void get_modified(Metrics::GetModifiedParams::RootReader *args, Metrics::GetModifiedResult::RootBuilder *res);
    void get_deletions(Metrics::GetDeletionsParams::RootReader *args, Metrics::GetDeletionsResult::RootBuilder *res);
};

}}
