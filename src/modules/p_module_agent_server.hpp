/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <limits.h>

#include "defs.hpp"
#include "modules/p_module.vproto.hpp"
#include "modules/p_module_agent.rpc.server.hpp"

namespace P {

class PModuleAgentServerImpl : public PModuleAgentServer {
public:
    void init(SiloId silo_id, ModuleId module_id, Conf::ConfigSetting *module_setting);

private:
    struct EnvData {
        GUID env_guid;
        pid_t pid;
    };

    // TODO: once the P-module's agent supports more functionality (leader election, monitoring, etc.), consider
    // splitting this class to several classes (launcher, monitoring, etc.). PModuleAgent will hold one object of each.

    // RPC functions:
    void set_local_env_id(SetLocalEnvIdParams::RootReader *args, VProto::Empty::RootBuilder *res);
    void env_start(EnvStartParams::RootReader *args, EnvStartResult::RootBuilder *res);
    void env_stop(EnvStopParams::RootReader *args, EnvStopResult::RootBuilder *res);
    void run_leader(VProto::Empty::RootReader *args, EnvStartResult::RootBuilder *res);
    void connect_device(ConnectDeviceParams::RootReader *args, ConnectDeviceResult::RootBuilder *res);
    void disconnect_device(DisconnectDeviceParams::RootReader *args, DisconnectDeviceResult::RootBuilder *res);
    void list_nvrams(VProto::Empty::RootReader *args, ListNVRAMsResult::RootBuilder *res);

    /*!
     * Helper function, used by env_start and run_leader to start an env.
     *
     * \param env_guid GUID for the env to start.
     * \param config config string - will be written to file. If nullptr (for the case of run_leader) - ignored.
     * \param res result.
     */
    void do_env_start(GUID env_guid, const char *config, EnvStartResult::RootBuilder *res);

    char _config_dir[PATH_MAX];

    // Used for maintaining env data in a compact, efficient way.
    // TODO: currently, the functionality of adding/removing envs is explicitly implemented in this class. Consider
    // generalizing it (by creating a template data structure) if it seems like it will be reused.
    EnvData _envs[MAX_ENVS_PER_CNODE - 1];  // We don't need an entry for our own env.
    uint16_t _n_envs = 0;

    // TODO: consider moving this state and logic to a class initialized only on the DNode (includes list_nvrams/test_add_nvram)
    void init_test_drives(Conf::ConfigSetting *nvrams_setting);
    void init_drives();

    NVRAMInfo::RootBuilder _nvrams[DNODE_NVRAM_COUNT];
    bool _nvrams_initialized;

};  // class PModuleAgentServerImpl

}  // namespace P
