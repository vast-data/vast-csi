#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "metrics_agent.rpc.server.hpp"

namespace P { namespace Metrics {

class MetricsAgent : public MetricsAgentServer {
public:
    void init(SiloId silo_id, ModuleId module_id)
    {
        tracker.init();
        register_server(silo_id, module_id);
    }

    Metrics::Tracker tracker;

private:
    void get_generations(Tracker::GetGenerationsParams *args, uint16_t request_len,
                         Tracker::GetGenerationsResult *res, uint16_t *reply_len);
    void get_modified(Tracker::GetModifiedParams *args, uint16_t request_len,
                      Tracker::GetModifiedResult *res, uint16_t *reply_len);

};

}}
