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

class DNode : public Object<DNodeProto, TypeId::DNode, BaseNode> {
public:
    virtual NodeBaseProto::Builder *get_node_base()
    {
        return get_base_node_proto();
    }
};

}
