/* Copyright (C) Vast Data Ltd. */
#include "component.hpp"
#include "internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/macros.hpp"
#include "control/imdb/cnode.hpp"
#include "control/imdb/env.hpp"

namespace Control {

void Cluster::system_init(SystemInitParams::RootReader *args, SystemInitResult::RootBuilder *res)
{
    _system->set_state(SystemState::ONLINE);
    PT_INFO(CONTROL, "System initialized. State is now ONLINE.");
    res->set_code(SystemInitResultCode::SUCCESS);
}

EnvObj *Cluster::create_env(const char *name)
{
    EnvObj *env = _imdb->create<EnvObj>(P::GUID::create());
    strcpy(env->get_base_proto()->get_name(), name);

    env->set_connected(false);
    env->set_id(_system->allocate_env_id());
    return env;
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

    LOOP(cnode->get_addresses_count(), i)
        *cnode->get_addresses(i) = *args->get_addresses(i);
    cnode->set_enabled(false);

    // create the child platform env
    cnode->add_child(create_env("platform"));

    // create the child data EnvObjs
    LOOP(args->get_env_count(), i) {
        cnode->add_child(create_env("data"));
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
    _imdb->remove(cnode);

    res->set_code(CNodeRemoveResultCode::SUCCESS);
}

}
