#include "agent.hpp"

namespace P { namespace Metrics {

void MetricsAgent::get_generations(Tracker::GetGenerationsParams *args, uint16_t request_len,
                                   Tracker::GetGenerationsResult *res, uint16_t *reply_len)
{
    tracker.get_generations(args, res);
    *reply_len = sizeof(Tracker::GetGenerationsResult);
}

void MetricsAgent::get_modified(Tracker::GetModifiedParams *args, uint16_t request_len,
                                Tracker::GetModifiedResult *res, uint16_t *reply_len)
{
    tracker.get_modified(args, res, reply_len);
}

}}
