/* Copyright (C) Vast Data Ltd. */

/*!
 * \file drive.hpp
 * \brief Drive object implementation.
 */
#pragma once

#include "drive.vproto.hpp"
#include "object.hpp"

namespace Control {

class Drive : public Object<DriveProto, TypeId::Drive> {
public:

};

}
