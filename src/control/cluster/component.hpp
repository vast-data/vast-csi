/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief The cluster component.
 */
#pragma once

#include "plasma/vmsg/vmsg.vproto.hpp"
#include "control/imdb/component.hpp"
#include "control/imdb/system.hpp"
#include "control/imdb/cnode.hpp"
#include "control/imdb/dbox.hpp"
#include "control/imdb/dnode.hpp"
#include "control/imdb/nvram.hpp"
#include "control/imdb/env.hpp"
#include "control/imdb/module.hpp"
#include "control/estore/estore.hpp"
#include "control/mio/mioc.hpp"
#include "cluster.rpc.server.hpp"

namespace Control {

class Cluster : public ClusterServer {
public:
    void init(P::SiloId silo_id, ModuleId module_id, TreeDB *imdb, System *system, MIOControl *mio, EStoreControl *estore);
    void start();
    void connect_envs();

private:
    // internal functions
    bool address_already_exists(char *host);
    void node_deactivate(BaseNode *node);

    void calc_cnode_state(CNode *cnode);
    void cnode_activate(CNode *cnode);
    void cnode_deactivate(CNode *cnode);

    void calc_dnode_state(DNode *dnode);
    void dnode_initialize(DNode *dnode);
    void dnode_activate(DNode *dnode);
    void dnode_deactivate(DNode *dnode);
    void initialize_all_dnodes();

    void nvram_activate(NVRAM *nvram);
    void nvram_deactivate(NVRAM *nvram);
    void connect_cnode_to_device(CNode *cnode, NVRAM *nvram);
    void prepare_disconnect_cnode_from_device(CNode *cnode, NVRAM *nvram);
    void disconnect_cnode_from_device(CNode *cnode, NVRAM *nvram);
    void connect_env_to_device(EnvObj *env, NVRAM *nvram, char *local_path);
    void prepare_disconnect_env_from_device(EnvObj *env, NVRAM *nvram);
    void disconnect_env_from_device(EnvObj *env, NVRAM *nvram);

    EnvObj *create_env(BaseNode *node, P::byte silo_count, uint16_t port);
    void env_activate(EnvObj *env);
    void env_start(EnvObj *env);
    void env_stop(EnvObj *env);
    void connect_env(EnvObj *env);
    void connect_data_env(EnvObj *env);
    void connect_platform_env(EnvObj *env);
    void connect_env_to_env(EnvObj *env1, EnvObj *env2);
    void connect_all_cnodes_to_node(BaseNode *node);
    void connect_all_dnodes_to_node(BaseNode *node);

    /*!
     * Run Func concurrently on all active cnodes and wait for all fibers to complete.
     *
     * Func is a method of this class that accepts a CNode and Param.
     * Param is an arbitrary parameter passed to method.
     */
    template <typename Func, typename Param>
    void map_on_cnodes(Func func, Param param);

    BaseTreeObject *create_module(EnvObj *env, ModuleId module_id, SiloId silo_id);

    // RPC functions
    void system_status(SystemStatusParams::RootReader *args, SystemStatusResult::RootBuilder *res);
    void system_activate(SystemActivateParams::RootReader *args, SystemActivateResult::RootBuilder *res);
    void system_redist(SystemRedistParams::RootReader *args, SystemRedistResult::RootBuilder *res);

    void cnode_add(CNodeAddParams::RootReader *args, CNodeAddResult::RootBuilder *res);
    void cnode_modify(CNodeModifyParams::RootReader *args, CNodeModifyResult::RootBuilder *res);
    void cnode_remove(CNodeRemoveParams::RootReader *args, CNodeRemoveResult::RootBuilder *res);
    void cnode_get(CNodeGetParams::RootReader *args, CNodeGetResult::RootBuilder *res);

    void dbox_add(DBoxAddParams::RootReader *args, DBoxAddResult::RootBuilder *res);
    void dbox_get(DBoxGetParams::RootReader *args, DBoxGetResult::RootBuilder *res);
    void dnode_modify(DNodeModifyParams::RootReader *args, DNodeModifyResult::RootBuilder *res);

    TreeDB *_tree;
    System *_system;
    MIOControl *_mio;
    EStoreControl *_estore;
    EnvObj *_local_env_obj;
};

}
