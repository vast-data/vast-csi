#include "../utils/assert.hpp"
#include "connection.hpp"

namespace P {
namespace VMsg {

void Connection::init(EnvId env_id, ModuleId module_id, LinkType link_type)
{
    _link.init(env_id, module_id, link_type);
}

void Connection::destroy()
{
    _link.destroy();
}

RDMALink *Connection::get_free_link()
{
    DEBUG_ASSERT(_link.get_state() == LinkState::IDLE);
    return &_link;
}

RDMALink *Connection::get_next_link()
{
    return &_link;
}


}
}
