#include "agent.hpp"

namespace P { namespace Metrics {

void MetricsAgent::get_generations(GetGenerationsParams::RootReader *args, GetGenerationsResult::RootBuilder *res)
{
    tracker.get_generations(args, res);
}

void MetricsAgent::get_modified(GetModifiedParams::RootReader *args, GetModifiedResult::RootBuilder *res)
{
    tracker.get_modified(args, res);
}

void MetricsAgent::get_deletions(GetDeletionsParams::RootReader *args, GetDeletionsResult::RootBuilder *res)
{
    tracker.get_deletions(args, res);
}

}}
