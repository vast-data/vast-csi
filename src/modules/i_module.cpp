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
    _created_estore = false;

    // Verify that the i-module config matches that of NFS.
    ConfigSetting *fibers_setting = conf_setting_lookup_required(setting, "fibers");
    uint32_t i_proto_fiber_count = 0;
    LOOP(conf_setting_length(fibers_setting), i) {
        ConfigSetting *fiber_group_setting = conf_setting_get_element(fibers_setting, (uint32_t) i);
        ConfigSetting *group_id_setting = conf_setting_lookup_required(fiber_group_setting, "group_id");
        FiberGroupId group_id = fiber_group_id_from_string(conf_setting_get_string(group_id_setting));
        if (group_id == FiberGroupId::I_PROTO) {
            ConfigSetting *count_setting = conf_setting_lookup_required(fiber_group_setting, "count");
            i_proto_fiber_count = conf_setting_get_int32(count_setting);
            break;
        }
    }
    ASSERT(i_proto_fiber_count != 0);
    ASSERT(NfsProto::get_nfs_conf()->enabled);
    ASSERT_EQUAL(NfsProto::get_nfs_conf()->requests_per_silo, i_proto_fiber_count);

    _nfs.init(&_estore, P::Env::get()->get_tcp_acceptor(), first_init);
    _dev_agent.init(silo->get_id(), get_id(), FiberGroupId::I_CONTROL);
    _mio.init(silo->get_id(), get_id(), (P::Index)FiberGroupId::I_MIO, &_dev_agent,
              MirroredIO::MIO::DEFAULT_CONCURRENT_READERS, MirroredIO::MIO::DEFAULT_CONCURRENT_WRITERS,
              MirroredIO::MIO::DEFAULT_DEVICES_ASYNCLY_WRITTEN);
    _agent.init(silo->get_id(), this);
    _estore.init(silo->get_id(), get_id(), FiberGroupId::I_CONTROL, &_mio);
    first_init = false;
}

static void nfs_poll_fiber(void *nfs_proto)
{
    NfsProto *nfs = (NfsProto *)nfs_proto;
    while (true) {
        nfs->poll();
        P::Fiber::yield();
        if (unlikely(global_env_stop)) {
            break;
        }
    }
}

void IModule::activate()
{
    if (!_created_estore)
        _estore.load();
    P::Fiber::init((P::Index)FiberGroupId::I_NFS_POLLING, nfs_poll_fiber, &_nfs, false);
}

void IModule::create_estore()
{
    _created_estore = true;
    _estore.create_estore();
}

void IModule::start()
{
    _dev_agent.start(FiberGroupId::I_IO_POLLING);
}

/* static */ void IModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 1, "I_NFS_POLLING");
    add_fiber_group_config(module_config, NfsProto::DEFAULT_REQUESTS_PER_SILO, "I_PROTO", 131072);
    add_fiber_group_config(module_config, 1, "I_IO_POLLING");
    add_fiber_group_config(module_config, 16, "I_MIO");
    add_fiber_group_config(module_config, 16, "I_CONTROL");
}

/* static */ void IModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    get_default_vmsg_module_resources(vmsg_module_resources);
}
