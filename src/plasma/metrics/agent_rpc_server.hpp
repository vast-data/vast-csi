#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "metrics_agent.rpc.server.hpp"

namespace P { namespace Metrics {

class MetricsAgentServerImpl : public MetricsAgentServer {
    void get_generations(Agent::GetGenerationsParams *args, uint16_t request_len,
                         Agent::GetGenerationsResult *res, uint16_t *reply_len);
    void get_modified(Agent::GetModifiedParams *args, uint16_t request_len,
                      Agent::GetModifiedResult *res, uint16_t *reply_len);
};

}}
