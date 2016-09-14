/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief The cluster component.
 */
#pragma once

#include "control/imdb/component.hpp"
#include "cluster.rpc.server.hpp"

namespace Control {

class Cluster : public ClusterServer {
public:
    void init(P::SiloId silo_id, ModuleId module_id, IMDB *imdb, System *system)
    {
        _imdb = imdb;
        _system = system;
        register_server(silo_id, module_id);
    }

private:
    EnvObj *create_env(const char *name, P::byte silo_count);
    template <class ModuleObj>
    ModuleObj *create_module(SiloId silo_id);

    void cnode_activate(CNode *cnode);
    void cnode_deactivate(CNode *cnode);

    // RPC functions
    void system_status(SystemStatusParams::RootReader *args, SystemStatusResult::RootBuilder *res);
    void system_init(SystemInitParams::RootReader *args, SystemInitResult::RootBuilder *res);
    void cnode_add(CNodeAddParams::RootReader *args, CNodeAddResult::RootBuilder *res);
    void cnode_modify(CNodeModifyParams::RootReader *args, CNodeModifyResult::RootBuilder *res);
    void cnode_remove(CNodeRemoveParams::RootReader *args, CNodeRemoveResult::RootBuilder *res);

    IMDB *_imdb;
    System *_system;
};

}
