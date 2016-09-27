/* Copyright (C) Vast Data Ltd. */

/*!
 * \file nvram.hpp
 * \brief NVRAM object implementation.
 */
#pragma once

#include "nvram.vproto.hpp"
#include "object.hpp"

namespace Control {

class NVRAM : public ControlObject<NVRAMProto, TypeId::NVRAM> {
public:

};

}
