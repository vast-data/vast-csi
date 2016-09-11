#include <signal.h>

#include "p_module_agent_server.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/os.hpp"

#define CURRENT_COMPONENT ComponentId::PLASMA

namespace P {

void PModuleAgentServerImpl::init(SiloId silo_id, ModuleId module_id)
{
    int res = snprintf(_config_dir, PATH_MAX, "%s/config", Env::get()->get_data_dir());
    ASSERT_OP(res, >, 0, "Error writing config dir");
    ASSERT_OP(res, <, PATH_MAX, "data dir path is too long for creating a config dir");
    ASSERT_OP(res + strlen("/") + 2 * sizeof(GUID) + strlen(".config"), <, PATH_MAX,
              "data dir path is too long for keeping config files");
    ensure_directory_exists(_config_dir);

    _n_envs = 0;
    register_server(silo_id, module_id, FiberGroupId::P);
}

void PModuleAgentServerImpl::set_local_env_id(SetLocalEnvIdParams::RootReader *args, uint16_t request_len,
                                              VProto::Empty::RootBuilder *res, uint16_t *reply_len)
{
    VMsg::EnvId env_id = args->get_env_id();
    Env::get()->get_vmsg()->set_local_env_id(env_id);
    *reply_len = sizeof(VProto::Empty);
}

void PModuleAgentServerImpl::env_start(EnvStartParams::RootReader *args, uint16_t request_len,
                                       EnvStartResult::RootBuilder *res, uint16_t *reply_len)
{
    ASSERT_OP(strlen(Env::get()->get_binary_path()), >, 0, "No binary path");
    *reply_len = sizeof(EnvStartResult);

    if (_n_envs >= NUM_ELEMENTS(_envs)) {
        PT_ERROR(CONTROL, "Can't start env because %d envs already exist", _n_envs);
        res->set_code(EnvStartResultCode::MAX_ENVS_CREATED);
        return;
    }

    GUID env_guid = args->get_env_guid();
    for (Index i = 0; i < _n_envs; ++i) {
        if (_envs[i].env_guid.equals(&env_guid)) {
            PT_ERROR(CONTROL, "Can't start env because GUID %lx%lx already exists",
                     env_guid.get_first_half(), env_guid.get_second_half());
            res->set_code(EnvStartResultCode::GUID_ALREADY_EXISTS);
            return;
        }
    }

    char config_file_path[PATH_MAX];
    sprintf(config_file_path, "%s/%lx%lx.config", _config_dir, env_guid.get_first_half(), env_guid.get_second_half());
    if (!string_to_file(config_file_path, args->get_config())) {
        PT_ERROR(CONTROL, "Failed to write config file %s", config_file_path);
        res->set_code(EnvStartResultCode::WRITE_FAILED);
        return;

    }

    pid_t pid = fork();
    if (pid == 0) {  // child process
        // This will only return on error..
        if (execl(Env::get()->get_binary_path(), Env::get()->get_binary_path(),
                  config_file_path, (char*)nullptr) == -1) {
            PANIC("execl failed using config file " << config_file_path << " with errno " << std::strerror(errno));
        }
        PANIC("Not supposed to get here..");
    } else if (pid > 0) {  // parent process
        EnvData *env = &_envs[_n_envs++];
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

void PModuleAgentServerImpl::env_stop(EnvStopParams::RootReader *args, uint16_t request_len,
                                      EnvStopResult::RootBuilder *res, uint16_t *reply_len)
{
    *reply_len = sizeof(EnvStopResult);

    GUID env_guid = args->get_env_guid();
    Index found = -1;
    for (Index i = 0; i < _n_envs; ++i) {
        if (_envs[i].env_guid.equals(&env_guid)) {
            found = i;
            break;
        }
    }
    if (found == -1) {
        PT_ERROR(CONTROL, "GUID %lx%lx not found", env_guid.get_first_half(), env_guid.get_second_half());
        res->set_code(EnvStopResultCode::GUID_NOT_FOUND);
        return;
    }

    pid_t pid = _envs[found].pid;
    --_n_envs;
    if (found > _n_envs) {
        _envs[found].env_guid = _envs[_n_envs].env_guid;
        _envs[found].pid = _envs[_n_envs].pid;
    }

    if (kill(pid, SIGKILL) == -1) {
        PT_ERROR(CONTROL, "Kill failed with errno %s", std::strerror(errno));
        res->set_code(EnvStopResultCode::KILL_FAILED);
        return;
    }

    res->set_code(EnvStopResultCode::SUCCESS);
}

}  // namespace P
