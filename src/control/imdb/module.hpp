/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module.hpp
 * \brief Control module objects.
 */
#pragma once

#include "module.vproto.hpp"
#include "object.hpp"

namespace Control {

class EModuleObj : public Object<EModuleProto, TypeId::EModule> {

};

class PModuleObj : public Object<PModuleProto, TypeId::EModule> {

};

}
