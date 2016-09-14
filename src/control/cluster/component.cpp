/* Copyright (C) Vast Data Ltd. */
#include "component.hpp"
#include "internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/macros.hpp"
#include "control/imdb/cnode.hpp"
#include "control/imdb/env.hpp"
#include "control/imdb/module.hpp"


namespace Control {

void Cluster::system_status(SystemStatusParams::RootReader *args, SystemStatusResult::RootBuilder *res)
{
    res->get_system()->init_from_reader(_system->as_reader());
}

void Cluster::system_init(SystemInitParams::RootReader *args, SystemInitResult::RootBuilder *res)
{
    _system->set_state(SystemState::ONLINE);
    PT_INFO(CONTROL, "System initialized. State is now ONLINE.");
    res->set_code(SystemInitResultCode::SUCCESS);
}

EnvObj *Cluster::create_env(const char *name, P::byte silo_count)
{
    EnvObj *env = _imdb->create<EnvObj>(P::GUID::create());
    strcpy(env->get_base_proto()->get_name(), name);

    env->set_silo_count(silo_count);
    env->set_connected(false);
    env->set_id(_system->allocate_env_id());
    return env;
}

template <class ModuleObj>
ModuleObj *Cluster::create_module(SiloId silo_id)
{
    ModuleObj *module = _imdb->create<ModuleObj>(P::GUID::create());
    module->get_base_module_proto()->set_state(ModuleState::OFFLINE);
    module->get_base_module_proto()->set_silo_id(silo_id);
    return module;
}

void Cluster::cnode_add(CNodeAddParams::RootReader *args, CNodeAddResult::RootBuilder *res)
{
    // create the CNode
    bool already_exists;
    CNode *cnode = _imdb->get_or_create<CNode>(args->get_guid(), &already_exists);
    if (cnode == nullptr) {
        res->set_code(CNodeAddResultCode::NO_MEM);
        return;
    }
    if (already_exists) {
        res->set_code(CNodeAddResultCode::ALREADY_EXISTS);
        return;
    }

    _system->add_child(cnode);
    sprintf(cnode->get_base_proto()->get_name(), "cnode-%03d", _system->allocate_cnode_id());

    LOOP(cnode->get_address_count(), i)
        *cnode->get_address(i) = *args->get_address(i);
    cnode->set_enabled(false);

    // create the child platform env
    EnvObj *env = create_env("platform", 1);
    cnode->add_child(env);
    env->add_child(create_module<EModuleObj>(0));
    env->add_child(create_module<PModuleObj>(0));

    // create the child data EnvObjs
    EnvConfig::Reader env_config;
    SiloConfig::Reader silo_config;
    LOOP(args->get_env_count(), env_index) {
        args->get_env_config(&env_config, env_index);
        env = create_env("data", env_config.get_silo_count());
        cnode->add_child(env);
        LOOP(env_config.get_silo_count(), silo_index) {
            env_config.get_silo_config(&silo_config, silo_index);
            LOOP(silo_config.get_module_enabled_count(), module_index) {
                if (silo_config.get_module_enabled(module_index))
                    switch ((ModuleId) module_index) {
                    case ModuleId::E:
                        env->add_child(create_module<EModuleObj>(silo_index));
                        break;
                    case ModuleId::P:
                        env->add_child(create_module<PModuleObj>(silo_index));
                        break;
                    default:
                        PANIC("Unknown module configured: " << module_id_to_string((ModuleId) module_index));
                    }
            }
        }
    }

    char guid_string[P::GUID::STRING_SIZE];
    args->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "CNode %s:%s added.", cnode->get_base_proto()->get_name(), guid_string);

    res->set_code(CNodeAddResultCode::SUCCESS);
}

void Cluster::cnode_modify(CNodeModifyParams::RootReader *args, CNodeModifyResult::RootBuilder *res)
{
    CNode *cnode = _imdb->get<CNode>(args->get_guid());
    if (cnode == nullptr) {
        res->set_code(CNodeModifyResultCode::NOT_FOUND);
        return;
    }
    cnode->set_enabled(args->get_enabled());
}

void Cluster::cnode_remove(CNodeRemoveParams::RootReader *args, CNodeRemoveResult::RootBuilder *res)
{
    CNode *cnode = _imdb->get<CNode>(args->get_guid());
    if (cnode == nullptr) {
        res->set_code(CNodeRemoveResultCode::NOT_FOUND);
        return;
    }
    if (cnode->get_enabled()) {
        res->set_code(CNodeRemoveResultCode::NOT_DISABLED);
        return;
    }

    char guid_string[P::GUID::STRING_SIZE];
    args->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "removing CNode %s:%s .", cnode->get_base_proto()->get_name(), guid_string);

    _imdb->remove(cnode);

    res->set_code(CNodeRemoveResultCode::SUCCESS);
}

}
