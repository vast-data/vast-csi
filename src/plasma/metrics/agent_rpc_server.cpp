#include "agent_rpc_server.hpp"

#include "plasma/execution/silo.hpp"

namespace P { namespace Metrics {

void AgentServerImpl::get_generations(Agent::GetGenerationsParams *args, uint16_t request_len,
                                      Agent::GetGenerationsResult *res, uint16_t *reply_len)
{
    Silo::get_module()->metrics_agent->get_generations(args, res);
    *reply_len = sizeof(Agent::GetGenerationsResult);
}

void AgentServerImpl::get_modified(Agent::GetModifiedParams *args, uint16_t request_len,
                                   Agent::GetModifiedResult *res, uint16_t *reply_len)
{
    Silo::get_module()->metrics_agent->get_modified(args, res, reply_len);
}

}}
