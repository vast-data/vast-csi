#include <cstdio>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>

#include "p_module_agent_server.hpp"
#include "e_module_agent_server.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/os.hpp"
#include "globals.hpp"

#define CURRENT_COMPONENT ComponentId::PLASMA

namespace P {

void PModuleAgentServerImpl::init(SiloId silo_id, ModuleId module_id, Conf::ConfigSetting *module_setting)
{
    _nvrams_initialized = false;
    Conf::ConfigSetting *nvrams_setting = Conf::conf_setting_lookup_optional(module_setting, "nvrams");
    if (nvrams_setting == nullptr)
        init_drives();
    else
        init_test_drives(nvrams_setting);

    int res = snprintf(_config_dir, PATH_MAX, "%s/config", Env::get()->get_data_dir());
    ASSERT_OP(res, >, 0, "Error writing config dir");
    ASSERT_OP(res, <, PATH_MAX, "data dir path is too long for creating a config dir");
    ASSERT_OP(res + strlen("/") + GUID::STRING_LENGTH + strlen(".config"), <, PATH_MAX,
              "data dir path is too long for keeping config files");
    ensure_directory_exists(_config_dir);

    _n_envs = 0;
    register_server(silo_id, module_id);

    ASSERT(VMsg::RDMATransport::fork_init());
}

void PModuleAgentServerImpl::init_drives()
{
    //TODO: how to scan for NVRAMs?
}

void PModuleAgentServerImpl::init_test_drives(Conf::ConfigSetting *nvrams_setting)
{
    ASSERT(global_test_mode);

    LOOP(Conf::conf_setting_length(nvrams_setting), i) {
        Conf::ConfigSetting *nvram_setting = Conf::conf_setting_get_element(nvrams_setting, (uint32_t) i);
        Conf::ConfigSetting *path_setting = Conf::conf_setting_lookup_required(nvram_setting, "path");
        const char *path = Conf::conf_setting_get_string(path_setting);
        Conf::ConfigSetting *size_setting = Conf::conf_setting_lookup_required(nvram_setting, "size");

        _nvrams[i].init();
        strcpy(_nvrams[i].get_path(), path);
        _nvrams[i].set_size(Conf::conf_setting_get_int64(size_setting));
        _nvrams[i].set_version(0);
    }

    _nvrams_initialized = true;
}

void PModuleAgentServerImpl::set_local_env_id(SetLocalEnvIdParams::RootReader *args, VProto::Empty::RootBuilder *res)
{
    // 1. Set local env ID:
    VMsg::EnvId env_id = args->get_env_id();
    Env::get()->get_vmsg()->set_local_env_id(env_id);
    PT_INFO(CONTROL, "Setting local env_id=%d", env_id);

    // 2. Set env addresses (of the caller, which is the Leader env):
    ConnectParams::Reader connect_params_reader;
    args->get_connect_params(&connect_params_reader);
    EModuleAgentServerImpl::do_connect(&connect_params_reader);
}

void PModuleAgentServerImpl::do_env_start(GUID env_guid, const char *config, EnvStartResult::RootBuilder *res)
{
    ASSERT_OP(strlen(Env::get()->get_binary_path()), >, 0, "No binary path");

    if (_n_envs >= NUM_ELEMENTS(_envs)) {
        PT_ERROR(CONTROL, "Can't start env because %d envs already exist", _n_envs);
        res->set_code(EnvStartResultCode::MAX_ENVS_CREATED);
        return;
    }

    char env_guid_str[GUID::STRING_SIZE];
    env_guid.to_string(env_guid_str);

    for (Index i = 0; i < _n_envs; ++i) {
        if (_envs[i].env_guid.equals(env_guid)) {
            PT_ERROR(CONTROL, "Can't start env because GUID %s already exists", env_guid_str);
            res->set_code(EnvStartResultCode::GUID_ALREADY_EXISTS);
            return;
        }
    }

    char config_file_path[PATH_MAX];
    sprintf(config_file_path, "%s/%s.config", _config_dir, env_guid_str);
    if (config != nullptr && !string_to_file(config_file_path, config)) {
        PT_ERROR(CONTROL, "Failed to write config file %s", config_file_path);
        res->set_code(EnvStartResultCode::WRITE_FAILED);
        return;

    }

    pid_t pid = fork();
    if (pid == 0) {  // child process
        P::kill_myself_on_parent_death();
        // This will only return on error..
        if (execl(Env::get()->get_binary_path(), Env::get()->get_binary_path(),
                  config_file_path, (char*)nullptr) == -1) {
            PANIC("execl failed using config file " << config_file_path << " with errno " << std::strerror(errno));
        }
        PANIC("Not supposed to get here..");
    } else if (pid > 0) {  // parent process
        EnvData *env = &_envs[_n_envs];
        PT_DEBUG(CONTROL, "Added env #%d, GUID=%s, pid=%d", _n_envs, env_guid_str, pid);
        ++_n_envs;
        env->env_guid = env_guid;
        env->pid = pid;
        res->set_code(EnvStartResultCode::SUCCESS);
        return;
    } else {  // fork failed
        PT_ERROR(CONTROL, "Fork failed with errno %s", std::strerror(errno));
        res->set_code(EnvStartResultCode::FORK_FAILED);
        return;
    }
    PANIC("Not supposed to get here..");
}

void PModuleAgentServerImpl::env_start(EnvStartParams::RootReader *args, EnvStartResult::RootBuilder *res)
{
    do_env_start(args->get_env_guid(), args->get_config(), res);
}

void PModuleAgentServerImpl::env_stop(EnvStopParams::RootReader *args, EnvStopResult::RootBuilder *res)
{
    GUID env_guid = args->get_env_guid();
    char env_guid_str[GUID::STRING_SIZE];
    env_guid.to_string(env_guid_str);

    Index found = -1;
    for (Index i = 0; i < _n_envs; ++i) {
        if (_envs[i].env_guid.equals(env_guid)) {
            found = i;
            break;
        }
    }
    if (found == -1) {
        PT_ERROR(CONTROL, "GUID %s not found", env_guid_str);
        res->set_code(EnvStopResultCode::GUID_NOT_FOUND);
        return;
    }

    pid_t pid = _envs[found].pid;
    --_n_envs;
    PT_DEBUG(CONTROL, "Removed env #%d, GUID %s", found, env_guid_str);
    if (found < _n_envs) {
        _envs[found].env_guid = _envs[_n_envs].env_guid;
        _envs[found].pid = _envs[_n_envs].pid;
    }

    if (kill(pid, SIGKILL) == -1) {
        PT_ERROR(CONTROL, "Kill failed with errno %s", std::strerror(errno));
        res->set_code(EnvStopResultCode::KILL_FAILED);
        return;
    }
    waitpid(pid, nullptr, 0);
    res->set_code(EnvStopResultCode::SUCCESS);
}

void PModuleAgentServerImpl::run_leader(VProto::Empty::RootReader *args, EnvStartResult::RootBuilder *res)
{
    GUID env_guid;
    ASSERT(env_guid.init_from_string(LEADER_ENV_GUID));

    // The config file for the leader env already exists, so we don't need to create it.
    do_env_start(env_guid, nullptr, res);
}

void PModuleAgentServerImpl::connect_device(ConnectDeviceParams::RootReader *args, ConnectDeviceResult::RootBuilder *res)
{
    // TODO: this function should connect the device using its guid (marks the subsystem) and dnode addresses
    // and return the path it's mounted on. if the device is already mounted, return its path anyways.
    if (global_test_mode) {
        char guid_string[P::GUID::STRING_SIZE];
        args->get_guid().to_string(guid_string);
        sprintf(res->get_path(), "/tmp/drives/%s", guid_string);
        close(open(res->get_path(), O_CREAT, S_IRUSR | S_IWUSR));
    } else {
        PANIC("Not implemented!");
    }
}

void PModuleAgentServerImpl::disconnect_device(DisconnectDeviceParams::RootReader *args, DisconnectDeviceResult::RootBuilder *res)
{
    // TODO: remove the nvme device
}

void PModuleAgentServerImpl::list_nvrams(VProto::Empty::RootReader *args, ListNVRAMsResult::RootBuilder *res)
{
    ASSERT(_nvrams_initialized);
    LOOP(res->get_nvrams_count(), i) {
        res->get_nvrams(i)->init_from_root(&_nvrams[i]);
    }
}

}  // namespace P
