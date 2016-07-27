#include "agent.hpp"

namespace P { namespace Metrics {

void MetricsAgent::get_generations(GetGenerationsParams::RootReader *args, uint16_t request_len,
                                   GetGenerationsResult::RootBuilder *res, uint16_t *reply_len)
{
    tracker.get_generations(args, res);
    *reply_len = sizeof(GetGenerationsResult);
}

void MetricsAgent::get_modified(GetModifiedParams::RootReader *args, uint16_t request_len,
                                GetModifiedResult::RootBuilder *res, uint16_t *reply_len)
{
    tracker.get_modified(args, res, reply_len);
}

void MetricsAgent::get_deletions(GetDeletionsParams::RootReader *args, uint16_t request_len,
                                 GetDeletionsResult::RootBuilder *res, uint16_t *reply_len)
{
    tracker.get_deletions(args, res, reply_len);
}

}}
