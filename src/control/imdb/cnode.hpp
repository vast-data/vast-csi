/* Copyright (C) Vast Data Ltd. */

/*!
 * \file cnode.hpp
 * \brief CNode object implementation.
 */
#pragma once

#include "cnode.vproto.hpp"
#include "object.hpp"
#include "node.hpp"

namespace Control {

class CNode : public ControlObject<CNodeProto, TypeId::CNode, BaseNode> {
public:
    virtual BaseNodeProto::Builder *get_base_node()
    {
        return get_base_node_proto();
    }
};

}
