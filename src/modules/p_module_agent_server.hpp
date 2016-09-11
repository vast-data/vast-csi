#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <limits.h>

#include "defs.hpp"
#include "modules/p_module.vproto.hpp"
#include "modules/p_module_agent.rpc.server.hpp"

namespace P {

class PModuleAgentServerImpl : public PModuleAgentServer {
public:
    void init(SiloId silo_id, ModuleId module_id);

private:
    struct EnvData {
        GUID env_guid;
        pid_t pid;
    };

    // TODO: once the P-module's agent supports more functionality (leader election, monitoring, etc.), consider
    // splitting this class to several classes (launcher, monitoring, etc.). PModuleAgent will hold one object of each.
    void set_local_env_id(SetLocalEnvIdParams::RootReader *args, VProto::Empty::RootBuilder *res);
    void env_start(EnvStartParams::RootReader *args, EnvStartResult::RootBuilder *res);
    void env_stop(EnvStopParams::RootReader *args, EnvStopResult::RootBuilder *res);

    char _config_dir[PATH_MAX];

    // Used for maintaining env data in a compact, efficient way.
    // TODO: currently, the functionality of adding/removing envs is explicitly implemented in this class. Consider
    // generalizing it (by creating a template data structure) if it seems like it will be reused.
    EnvData _envs[MAX_ENVS];
    uint16_t _n_envs = 0;
};  // class PModuleAgentServerImpl

}  // namespace P
