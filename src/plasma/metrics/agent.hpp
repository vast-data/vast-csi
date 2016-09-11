#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/metrics/metrics_agent.rpc.server.hpp"
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
    void get_generations(Metrics::GetGenerationsParams::RootReader *args, uint16_t request_len,
                         Metrics::GetGenerationsResult::RootBuilder *res, uint16_t *reply_len);
    void get_modified(Metrics::GetModifiedParams::RootReader *args, uint16_t request_len,
                      Metrics::GetModifiedResult::RootBuilder *res, uint16_t *reply_len);
    void get_deletions(Metrics::GetDeletionsParams::RootReader *args, uint16_t request_len,
                       Metrics::GetDeletionsResult::RootBuilder *res, uint16_t *reply_len);
};

}}
