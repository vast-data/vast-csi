#include "vmsg_defs.hpp"
#include "plasma/execution/env.hpp"

namespace P { namespace VMsg {

void free_vmsg_response(void *buffer)
{
    if (buffer != nullptr)
        P::Env::get()->get_vmsg()->free_received_response(buffer);
}

}}
