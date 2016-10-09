/* Copyright (C) Vast Data Ltd. */

#include "module.hpp"
#include "modules/c_module.hpp"
#include "modules/i_module_agent.rpc.client.hpp"
#include "plasma/execution/silo.hpp"

namespace Control {

void IModuleObj::activate()
{
    CModule *c_module = dynamic_cast<CModule*>(P::Silo::get_module());
    ASSERT_NOT_NULL(c_module);
    c_module->get_estore_control()->activate_module(this);
    c_module->get_mio_control()->activate_module(this);
    c_module->get_estore_control()->ensure_created(this);

    IModuleAgentClient client;
    client.init();

    P::VProto::Empty::RootBuilder *params = client.alloc_activate();
    if (client.activate_sync(get_address(), params) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
}

}  // namespace Control
