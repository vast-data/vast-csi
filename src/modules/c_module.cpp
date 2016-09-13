/* Copyright (C) Vast Data Ltd. */
#include "c_module.hpp"
#include "plasma/utils/os.hpp"
#include "plasma/vmsg/vmsg.hpp"
#include "plasma/execution/env.hpp"
#include "control/imdb/system.hpp"

using namespace P;

namespace Control {

GUID get_system_guid()
{
    char system_guid_path[PATH_MAX];

    int res = snprintf(system_guid_path, PATH_MAX, "%s/system.guid", Env::get()->get_data_dir());
    ASSERT(res > 0 && res < PATH_MAX, "Error composing system guid path");

    char content[GUID::STRING_LENGTH + 1];
    bool success = file_to_string(system_guid_path, GUID::STRING_LENGTH + 1, content);
    ASSERT(success == true, "Failed reading system guid from path: " << system_guid_path);

    GUID result;
    success = result.init_from_string(content);
    ASSERT(success == true, "Failed parsing system guid from string: " << content);
    return result;
}

void CModule::init(P::Silo *silo, P::Conf::ConfigSetting *module_setting)
{
    _tree.init();

    GUID system_guid = get_system_guid();
    _system = _tree.create<System>(system_guid, nullptr);
    _system->get_base_proto()->set_parent_guid(system_guid); // the system is the root and points to itself.
    strcpy(_system->get_base_proto()->get_name(), "system");

    _system->set_next_cnode_id(1);
    _system->set_next_env_id(2); // 0 is reserved for platform envs and 1 is the leader
    _system->set_state(SystemState::INIT);

    _agent.init(silo->get_id(), get_id(), FiberGroupId::C);
    _cluster.init(silo->get_id(), get_id(), &_tree, _system);

    // TODO: these calls should be removed - see ticket ORION-65
    Env::get()->get_vmsg()->add_module_pair(ModuleId::TEST, ModuleId::C, VMsg::TransportType::RDMA);
    Env::get()->get_vmsg()->add_module_pair(ModuleId::C, ModuleId::P, VMsg::TransportType::RDMA);
}

void CModule::start()
{
    _cluster.start();
}

/* static */ void CModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 10, "C");
}

/* static */ void CModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
}

} // namespace Control
