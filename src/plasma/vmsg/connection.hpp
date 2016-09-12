/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_connection.hpp
 * \brief Repentants a connection with a remote Env on top of multiple links.
 * Note: multi link support is not yet implemented so for now the connection class only contains a single link.
 *
 */

#pragma once

#include "rdma_link.hpp"

namespace P {
namespace VMsg {

class Connection {
public:
    void init(EnvId env_id, ModuleId module_id, LinkType link_type);
    void destroy();

    RDMALink *get_free_link();
    RDMALink *get_next_link();

private:
    RDMALink _link;
};

}
}
