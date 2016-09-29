/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dnode.hpp
 * \brief DNode object implementation.
 */
#pragma once

#include "dnode.vproto.hpp"
#include "object.hpp"
#include "node.hpp"

namespace Control {

class DNode : public ControlObject<DNodeProto, TypeId::DNode, BaseNode> {
public:
    virtual BaseNodeProto::Builder *get_base_node()
    {
        return get_base_node_proto();
    }
};

}
