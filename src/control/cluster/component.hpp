/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief The cluster component.
 */
#pragma once

#include "plasma/vmsg/vmsg.vproto.hpp"
#include "control/imdb/component.hpp"
#include "cluster.rpc.server.hpp"

namespace Control {

const uint16_t PLATFORM_ENV_PORT = 4000;
const uint16_t PLATFORM_ENV_INITIAL_ID = 0;
const uint16_t LEADER_ENV_ID = 1;

class Cluster : public ClusterServer {
public:
    void init(P::SiloId silo_id, ModuleId module_id, TreeDB *imdb, System *system);
    void start();
    void connect_envs();

private:
    void calc_cnode_state(CNode *cnode);
    void cnode_activate(CNode *cnode);
    void cnode_deactivate(CNode *cnode);

    EnvObj *create_env(CNode *cnode, const char *name, P::byte silo_count, uint16_t port);
    void env_activate(EnvObj *env);
    void env_start(EnvObj *env);
    void env_stop(EnvObj *env);
    void connect_env(EnvObj *env);
    void connect_data_env(EnvObj *env);
    void connect_platform_env(EnvObj *env);
    void connect_env_to_env(EnvObj *env1, EnvObj *env2);

    ObjectBase *create_module(EnvObj *env, ModuleId module_id, SiloId silo_id);

    // RPC functions
    void system_status(SystemStatusParams::RootReader *args, SystemStatusResult::RootBuilder *res);
    void system_init(SystemInitParams::RootReader *args, SystemInitResult::RootBuilder *res);
    void cnode_add(CNodeAddParams::RootReader *args, CNodeAddResult::RootBuilder *res);
    void cnode_modify(CNodeModifyParams::RootReader *args, CNodeModifyResult::RootBuilder *res);
    void cnode_remove(CNodeRemoveParams::RootReader *args, CNodeRemoveResult::RootBuilder *res);
    void cnode_get(CNodeGetParams::RootReader *args, CNodeGetResult::RootBuilder *res);

    TreeDB *_tree;
    System *_system;
};

}
