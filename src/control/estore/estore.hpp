/* Copyright (C) Vast Data Ltd. */
#include "control/imdb/system.hpp"
#include "control/imdb/module.hpp"
#include "control/mio/mioc.hpp"
#include "modules/i_module_agent.rpc.client.hpp"
#include "plasma/fiber/sync/event.hpp"
#include "phys/layout/section_allocator.rpc.client.hpp"

namespace Control {

class EStoreControl {
public:
    void init(System *system, MIOControl *mio)
    {
        _system = system;
        _mio = mio;
        _created = false; //TODO: persist this information.
        _creating = false;
        _created_event.init();
    }

    void ensure_created(IModuleObj *module)
    {
        if (_created)
            return;
        if (_creating) {
            _created_event.wait();
            return;
        }
        _creating = true;

        IModuleAgentClient client;
        client.init();

        P::VProto::Empty::RootBuilder *params = client.alloc_create_estore();
        if (client.create_estore_sync(module->get_address(), params) != P::VMsg::VMsgRes::OK) {
            PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
        }

        _created_event.release_all();
        _created = true;
    }

    void activate_module(BaseModuleLogic *module)
    {
        Layout::SectionAllocatorClient client;
        client.init();

        Layout::SectionAllocatorActivateParams::RootBuilder *params = client.alloc_activate();
        params->set_estore_shard_count(_system->get_estore_shard_count());
        params->set_max_section_id(_mio->get_num_sections() - 1);
        if (client.activate_sync(module->get_address(), params) != P::VMsg::VMsgRes::OK) {
            PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
        }
    }

private:
    System *_system;
    MIOControl *_mio;

    P::FiberSync::Event _created_event;
    bool _created;
    bool _creating;
};

}
