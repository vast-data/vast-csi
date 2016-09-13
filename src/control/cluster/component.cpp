/* Copyright (C) Vast Data Ltd. */
#include "component.hpp"
#include "internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/vproto/vproto.hpp"
#include "modules/p_module_agent.rpc.client.hpp"
#include "modules/e_module_agent.rpc.client.hpp"
#include "control/imdb/cnode.hpp"
#include "control/imdb/env.hpp"
#include "control/imdb/module.hpp"

namespace Control {

void Cluster::init(P::SiloId silo_id, ModuleId module_id, TreeDB *tree, System *system)
{
    _tree = tree;
    _system = system;
    register_server(silo_id, module_id);
}

static void connect_envs_fiber(void *cluster_arg)
{
    Cluster *cluster = (Cluster*) cluster_arg;
    cluster->connect_envs();
}

void Cluster::start()
{
    P::Fiber *fiber = P::Fiber::init((P::Index)FiberGroupId::C, connect_envs_fiber, this);
    ASSERT_NOT_NULL(fiber);
}

void Cluster::connect_envs()
{
    IMDB_ITER_CHILDREN(_system, cnode, CNode, {
        IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
            connect_env(env);
        });
    });
}

void Cluster::connect_platform_env(EnvObj *env)
{
    // a platform env requires setting its env_id. the set_env_id RPC also connects back to me.
    P::PModuleAgentClient client;
    client.init();

    P::SetLocalEnvIdParams::RootBuilder *params = client.alloc_set_local_env_id();
    params->set_env_id(env->get_id());
    P::ConnectParams::Builder *connect_params = params->get_connect_params();
    connect_params->set_env_id(P::Env::get()->get_vmsg()->get_local_env_id());
    P::Env::get()->get_vmsg()->copy_env_addresses(connect_params->get_env_id(), connect_params->get_addresses());
    // TODO: make sure this function can be called more than once on an env. (the leader might be down and the platform could restart)
    PModuleObj *module = env->get_only_child<PModuleObj>();
    P::VProto::Empty::RootReader *result;
    if (client.set_local_env_id_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        char guid_string[P::GUID::STRING_SIZE];
        env->get_base()->get_guid().to_string(guid_string);
        PT_ERROR(CONTROL, "Error setting platform env id for env=%s", guid_string);
        return;
    }
    client.free_set_local_env_id(result);
}

void Cluster::connect_data_env(EnvObj *env)
{
    // any env other than the platform can be simply connected back to me.
    P::EModuleAgentClient client;
    client.init();

    P::ConnectParams::RootBuilder *params = client.alloc_connect();
    params->set_env_id(P::Env::get()->get_vmsg()->get_local_env_id());
    P::Env::get()->get_vmsg()->copy_env_addresses(params->get_env_id(), params->get_addresses());
    EModuleObj *module = env->get_only_child<EModuleObj>();
    P::VProto::Empty::RootReader *result;
    if (client.connect_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        char guid_string[P::GUID::STRING_SIZE];
        env->get_base()->get_guid().to_string(guid_string);
        PT_ERROR(CONTROL, "Error requesting env=%s to connect back to me", guid_string);
        return;
    }
    client.free_connect(result);
}

void Cluster::connect_env_to_env(EnvObj *env1, EnvObj *env2)
{
    P::EModuleAgentClient client;
    client.init();

    P::ConnectParams::RootBuilder *params = client.alloc_connect();
    params->set_env_id(env2->get_id());
    P::Env::get()->get_vmsg()->copy_env_addresses(env2->get_id(), params->get_addresses());
    EModuleObj *module = env1->get_only_child<EModuleObj>();
    P::VProto::Empty::RootReader *result;
    if (client.connect_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        char guid_string[P::GUID::STRING_SIZE];
        env1->get_base()->get_guid().to_string(guid_string);
        PT_ERROR(CONTROL, "Error requesting env=%s to connect back to me", guid_string);
        return;
    }
    client.free_connect(result);
}

void Cluster::connect_env(EnvObj *env)
{
    P::VMsg::EnvAddresses::RootBuilder addresses;
    CNode *cnode = (CNode*) env->get_parent();
    addresses.set_n_addr(cnode->get_addresses_count());
    LOOP(cnode->get_addresses_count(), i) {
        strcpy(addresses.get_addresses(i)->get_host(),
               cnode->get_addresses(i)->get_host());
        addresses.get_addresses(i)->set_port(env->get_port());
    }

    char guid_string[P::GUID::STRING_SIZE];
    env->get_base()->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Connecting to env=%s", guid_string);

    // connect to the env.
    P::Env::get()->get_vmsg()->set_env_addresses(env->get_id(), &addresses);

    P::VProto::Empty::RootReader *result;
    // tell the env to connect back to me.
    if (env->get_port() == PLATFORM_ENV_PORT) {
        connect_platform_env(env);
    } else {
        connect_data_env(env);
    }
}

void Cluster::system_status(SystemStatusParams::RootReader *args, SystemStatusResult::RootBuilder *res)
{
    res->get_system()->init_from_reader(_system->as_reader());
}

void Cluster::system_init(SystemInitParams::RootReader *args, SystemInitResult::RootBuilder *res)
{
    _system->set_state(SystemState::ONLINE);
    PT_INFO(CONTROL, "System initialized. State is now ONLINE.");

    // potentially activate all cnodes
    IMDB_ITER_CHILDREN(_system, cnode, CNode, {
        calc_cnode_state(cnode);
    });
    res->set_code(SystemInitResultCode::SUCCESS);
}

EnvObj *Cluster::create_env(CNode *cnode, const char *name, P::byte silo_count, uint16_t port)
{
    EnvObj *env = _tree->create<EnvObj>(P::GUID::create(), cnode);
    strcpy(env->get_base_proto()->get_name(), name);

    env->set_state(EnvState::INIT);
    env->set_silo_count(silo_count);
    env->set_port(port);
    env->set_connected(false);
    env->set_id(_system->allocate_env_id());
    return env;
}

ObjectBase *Cluster::create_module(EnvObj *env, ModuleId module_id, SiloId silo_id)
{
    ObjectBase *object = ModuleRegistry::get(module_id)->create_control_object(_tree, env);
    BaseModuleLogic *module = (BaseModuleLogic*) object;
    module->get_base_module()->set_state(ModuleState::OFFLINE);
    module->get_base_module()->set_silo_id(silo_id);
    return object;
}

void Cluster::calc_cnode_state(CNode *cnode)
{
    if (_system->get_state() == SystemState::ONLINE && cnode->get_enabled()) {
        if (cnode->get_state() == CNodeState::INACTIVE)
            cnode_activate(cnode);
    } else {
        if (cnode->get_state() == CNodeState::ACTIVE)
            cnode_deactivate(cnode);
    }
}

void Cluster::env_activate(EnvObj *env)
{
    IMDB_ITER_MODULES(env, module, {
        module->activate();
        char guid_string[P::GUID::STRING_SIZE];
        module->get_base()->get_guid().to_string(guid_string);
        PT_INFO(CONTROL, "Activated module=%s", guid_string);
    });
    env->set_state(EnvState::ACTIVE);
}

void Cluster::env_start(EnvObj *env)
{
    char guid_string[P::GUID::STRING_SIZE];
    env->get_base()->get_guid().to_string(guid_string);

    P::PModuleAgentClient client;
    client.init();

    P::EnvStartParams::RootBuilder *params = client.alloc_env_start();
    params->set_env_guid(env->get_base()->get_guid());
    const char *config = ""; //TODO: once configuration is ready, call it from here.
    strcpy(params->get_config(), config);
    P::EnvStartResult::RootReader *result;
    PModuleObj *module = env->get_only_child<PModuleObj>();
    if (client.env_start_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        PT_ERROR(CONTROL, "Error starting env=%s", guid_string);
        return;
    }
    P::EnvStartResultCode code = result->get_code();
    client.free_env_start(result);
    if (code != P::EnvStartResultCode::SUCCESS)
        PT_ERROR(CONTROL, "Error starting env=%s with code=%hhd", guid_string, code);
}

void Cluster::env_stop(EnvObj *env)
{
    char guid_string[P::GUID::STRING_SIZE];
    env->get_base()->get_guid().to_string(guid_string);

    P::PModuleAgentClient client;
    client.init();

    P::EnvStopParams::RootBuilder *params = client.alloc_env_stop();
    params->set_env_guid(env->get_base()->get_guid());
    P::EnvStopResult::RootReader *result;
    PModuleObj *module = env->get_only_child<PModuleObj>();
    if (client.env_stop_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        PT_ERROR(CONTROL, "Error setting platform env id for env=%s", guid_string);
        return;
    }
    P::EnvStopResultCode code = result->get_code();
    client.free_env_stop(result);
    if (code != P::EnvStopResultCode::SUCCESS)
        PT_ERROR(CONTROL, "Error stoping env=%s with code=%hhd", guid_string, code);
}

void Cluster::cnode_activate(CNode *cnode)
{
    // 1. start envs on this node.
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        if (env->get_port() == PLATFORM_ENV_PORT)
            continue;
        env_start(env);
    });

    // 2. interconnect the envs on this with the rest of the envs in the system.
    IMDB_ITER_CHILDREN(_system, other_cnode, CNode, {
        if (cnode == other_cnode)
            continue;
        IMDB_ITER_CHILDREN(other_cnode, other_env, EnvObj, {
            if (other_env->get_port() == PLATFORM_ENV_PORT)
                continue;
            IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
                if (env->get_port() == PLATFORM_ENV_PORT)
                    continue;
                connect_env_to_env(env, other_env);
                connect_env_to_env(other_env, env);
            });
        });
    });

    // 3. activate the envs.
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        env_activate(env);
    });

    char guid_string[P::GUID::STRING_SIZE];
    cnode->get_base()->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Activated cnode=%s", guid_string);
    cnode->set_state(CNodeState::ACTIVE);
}

void Cluster::cnode_deactivate(CNode *cnode)
{
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        if (env->get_port() == PLATFORM_ENV_PORT)
            continue;
        env_stop(env);
    });

    char guid_string[P::GUID::STRING_SIZE];
    cnode->get_base()->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Deactivated cnode=%s", guid_string);

    cnode->set_state(CNodeState::INACTIVE);
}

void Cluster::cnode_add(CNodeAddParams::RootReader *args, CNodeAddResult::RootBuilder *res)
{
    // create the CNode
    bool already_exists;
    CNode *cnode = _tree->get_or_create<CNode>(args->get_guid(), &already_exists, _system);
    if (cnode == nullptr) {
        res->set_code(CNodeAddResultCode::NO_MEM);
        return;
    }
    if (already_exists) {
        res->set_code(CNodeAddResultCode::ALREADY_EXISTS);
        return;
    }

    sprintf(cnode->get_base_proto()->get_name(), "cnode-%03d", _system->allocate_cnode_id());

    CNodeAddress::Reader address;
    LOOP(cnode->get_addresses_count(), i) {
        args->get_addresses(&address, i);
        cnode->get_addresses(i)->init_from_reader(&address);
    }
    cnode->set_enabled(false);
    cnode->set_state(CNodeState::INACTIVE);

    // create the child platform env
    EnvObj *env = create_env(cnode, "platform", 1, PLATFORM_ENV_PORT);
    create_module(env, ModuleId::E, 0);
    create_module(env, ModuleId::P, 0);
    connect_env(env);

    // create the child data EnvObjs
    EnvConfig::Reader env_config;
    SiloConfig::Reader silo_config;
    LOOP(args->get_env_count(), env_index) {
        args->get_env_configs(&env_config, env_index);
        env = create_env(cnode, "data", env_config.get_silo_count(), env_config.get_port());
        LOOP(env_config.get_silo_count(), silo_index) {
            env_config.get_silo_configs(&silo_config, silo_index);
            env->get_silos(silo_index)->set_affinity(silo_config.get_affinity());
            LOOP(silo_config.get_modules_enabled_count(), module_index) {
                if (silo_config.get_modules_enabled(module_index))
                    create_module(env, (ModuleId) module_index, silo_index);
            }
        }
    }

    char guid_string[P::GUID::STRING_SIZE];
    args->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Added cnode=%s", guid_string);

    res->set_code(CNodeAddResultCode::SUCCESS);
}

void Cluster::cnode_modify(CNodeModifyParams::RootReader *args, CNodeModifyResult::RootBuilder *res)
{
    CNode *cnode = _tree->get<CNode>(args->get_guid());
    if (cnode == nullptr) {
        res->set_code(CNodeModifyResultCode::NOT_FOUND);
        return;
    }

    char guid_string[P::GUID::STRING_SIZE];
    args->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Modified cnode=%s: enabled=%c", guid_string, args->get_enabled());

    cnode->set_enabled(args->get_enabled());
    calc_cnode_state(cnode);

    res->set_code(CNodeModifyResultCode::SUCCESS);
}

void Cluster::cnode_remove(CNodeRemoveParams::RootReader *args, CNodeRemoveResult::RootBuilder *res)
{
    CNode *cnode = _tree->get<CNode>(args->get_guid());
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
    PT_INFO(CONTROL, "Removing cnode=%s", guid_string);

    _tree->remove(cnode);

    res->set_code(CNodeRemoveResultCode::SUCCESS);
}

void Cluster::cnode_get(CNodeGetParams::RootReader *args, CNodeGetResult::RootBuilder *res)
{
    CNode *cnode = _tree->get<CNode>(args->get_guid());
    if (cnode == nullptr) {
        res->set_code(CNodeGetResultCode::NOT_FOUND);
        return;
    }
    res->get_cnode()->init_from_reader(cnode->as_reader());
    res->set_code(CNodeGetResultCode::SUCCESS);
}

}
