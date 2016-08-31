/* Copyright (C) Vast Data Ltd. */

/*!
 * \file cnode.hpp
 * \brief CNode object implementation.
 */
#pragma once

#include "cnode.vproto.hpp"
#include "object.hpp"

namespace Control {

class CNode : public Object<CNodeProto, TypeId::CNode> {
public:

};

}
