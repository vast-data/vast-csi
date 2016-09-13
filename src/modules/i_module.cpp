#include <stdio.h>
#include <globals.hpp>
#include "i_module.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/execution/silo.hpp"

using namespace P::Conf;
using P::Silo;
using Nfs::NfsProto;

void IModule::init(Silo *silo, ConfigSetting *setting)
{
    // allows us to know if this is the first module initialized.
    static bool first_init = true;

    _estore.init();
    _nfs.init(&_estore, P::Env::get()->get_tcp_acceptor(), first_init);
    _agent.init(silo->get_id(), get_id(), FiberGroupId::I_CONTROL);
    first_init = false;
}

static void nfs_poll_fiber(void *nfs_proto)
{
    NfsProto *nfs = (NfsProto *)nfs_proto;
    while (true) {
        nfs->poll();
        P::Fiber::yield();
        if (unlikely(env_stop)) {
            break;
        }
    }
}

void IModule::start()
{
    P::Fiber::init((P::Index)FiberGroupId::I_NFS_POLLING, nfs_poll_fiber, &_nfs, false);
}

/* static */ void IModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 1, "I_NFS_POLLING");
    add_fiber_group_config(module_config, 10, "I_PROTO");
    add_fiber_group_config(module_config, 10, "I_CONTROL");
}

/* static */ void IModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
}
