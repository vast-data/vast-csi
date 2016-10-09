/* Copyright (C) Vast Data Ltd. */
#include "control/imdb/system.hpp"
#include "control/imdb/module.hpp"
#include "phys/layout/section_allocator.rpc.client.hpp"

namespace Control {

class EStoreControl {
public:
    void init(System *system)
    {
        _system = system;
    }

    void activate_module(BaseModuleLogic *module)
    {
        Layout::SectionAllocatorClient client;
        client.init();

        Layout::SectionAllocatorActivateParams::RootBuilder *params = client.alloc_activate();
        params->set_estore_shard_count(_system->get_estore_shard_count());
        params->set_max_section_id(get_section_count());
        P::VProto::Empty::RootReader *result;
        if (client.activate_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
            PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
        }
    }

private:
    uint32_t get_section_count()
    {
        return 0;
    }

    System *_system;
};

}
