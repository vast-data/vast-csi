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
    _agent.init(silo->get_id(), get_id());
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
    P::Fiber::init((P::Index)FiberGroupId::NFS_POLLING, nfs_poll_fiber, &_nfs, false);
}

