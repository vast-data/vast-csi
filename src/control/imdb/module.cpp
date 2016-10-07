/* Copyright (C) Vast Data Ltd. */

#include "module.hpp"
#include "modules/c_module.hpp"
#include "plasma/execution/silo.hpp"

namespace Control {

void IModuleObj::activate()
{
    CModule *c_module = dynamic_cast<CModule*>(P::Silo::get_module());
    ASSERT_NOT_NULL(c_module);
    c_module->get_mio_control()->activate_module(this);
}

}  // namespace Control
