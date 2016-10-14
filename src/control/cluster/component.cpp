/* Copyright (C) Vast Data Ltd. */
#include "component.hpp"
#include "internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/fiber/runnable.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/utils/units.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/vproto/vproto.hpp"
#include "modules/p_module_agent.rpc.client.hpp"
#include "modules/e_module_agent.rpc.client.hpp"
#include "control/dev_agent/dev_agent.rpc.client.hpp"

using P::VMsg::RpcGuard;

namespace Control {

template  <class T>
static void set_env_modules(EnvObj *env, T connect_params) {
    LOOP(MODULES_COUNT, i) {
        *connect_params->get_modules(i) = false;
    }

    IMDB_ITER_MODULES(env, module, {
        *connect_params->get_modules((P::byte) module->get_module_id()) = true;
    });
}

static bool node_has_address(BaseNode *node, char *host)
{
    // check if a cnode or a dnode has a given address
    LOOP(node->get_base_node()->get_addresses_count(), i)
        if (strncmp(host,
                    node->get_base_node()->get_addresses(i)->get_host(),
                    node->get_base_node()->get_addresses_count()) == 0)
            return true;
    return false;
}

bool Cluster::address_already_exists(char *host)
{
    if (strcmp(host, P::LOCALHOST) == 0)
        return false; // it's allowed to run several nodes only on localhost

    IMDB_ITER_CHILDREN(_system, cnode, CNode, {
        if (node_has_address(cnode, host))
            return true;
    });
    IMDB_ITER_CHILDREN(_system, dbox, DBox, {
        IMDB_ITER_CHILDREN(dbox, dnode, DNode, {
            if (node_has_address(dnode, host))
                return true;
        });
    });
    return false;
}

void Cluster::init(P::SiloId silo_id, ModuleId module_id, TreeDB *tree, System *system, MIOControl *mio, EStoreControl *estore)
{
    _tree = tree;
    _system = system;
    _mio = mio;
    _estore = estore;
    register_server(silo_id, module_id);
    _local_env_obj = _tree->create<EnvObj>(P::GUID::create(), nullptr);
    _tree->create<CModuleObj>(P::GUID::create(), _local_env_obj);
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
    set_env_modules(_local_env_obj, params->get_connect_params());
    // TODO: make sure this function can be called more than once on an env. (the leader might be down and the platform could restart)
    PModuleObj *module = env->get_only_child<PModuleObj>();
    if (client.set_local_env_id_sync(module->get_address(), params) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
}

void Cluster::connect_data_env(EnvObj *env)
{
    // any env other than the platform can be simply connected back to me.
    P::EModuleAgentClient client;
    client.init();

    P::ConnectParams::RootBuilder *params = client.alloc_connect();
    params->set_env_id(P::Env::get()->get_vmsg()->get_local_env_id());
    P::Env::get()->get_vmsg()->copy_env_addresses(params->get_env_id(), params->get_addresses());
    set_env_modules(_local_env_obj, params);
    EModuleObj *module = env->get_only_child<EModuleObj>();
    if (client.connect_sync(module->get_address(), params) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
}

void Cluster::connect_env_to_env(EnvObj *env1, EnvObj *env2)
{
    P::EModuleAgentClient client;
    client.init();

    PT_INFO(CONTROL, "Connecting between env_id=%d and env_id=%d", env1->get_id(), env2->get_id());

    P::ConnectParams::RootBuilder *params = client.alloc_connect();
    params->set_env_id(env2->get_id());
    P::Env::get()->get_vmsg()->copy_env_addresses(env2->get_id(), params->get_addresses());
    set_env_modules(env2, params);
    EModuleObj *module = env1->get_only_child<EModuleObj>();
    if (client.connect_sync(module->get_address(), params) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
}

void Cluster::connect_env(EnvObj *env)
{
    P::VMsg::EnvAddresses::RootBuilder addresses;
    addresses.init();
    CNode *cnode = env->get_parent<CNode>();
    addresses.set_n_addr(cnode->get_base_node()->get_addresses_count());
    LOOP(cnode->get_base_node()->get_addresses_count(), i) {
        strcpy(addresses.get_addresses(i)->get_host(),
               cnode->get_base_node()->get_addresses(i)->get_host());
        addresses.get_addresses(i)->set_port(env->get_port());
    }

    char guid_string[P::GUID::STRING_SIZE];
    env->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Connecting to env=%s id=%d", guid_string, env->get_id());

    P::EnvModules env_modules = { 0 };
    IMDB_ITER_MODULES(env, module, {
        env_modules.env_modules[(P::byte)module->get_module_id()] = true;
    });

    // connect to the env.
    P::Env::get()->get_vmsg()->set_env_addresses(env->get_id(), &addresses, &env_modules);

    // tell the env to connect back to me.
    if (env->is_platform()) {
        connect_platform_env(env);
    } else {
        connect_data_env(env);
    }

    PT_INFO(CONTROL, "Connected to env=%s id=%d", guid_string, env->get_id());

    env->set_connected(true);
}

void Cluster::system_status(SystemStatusParams::RootReader *args, SystemStatusResult::RootBuilder *res)
{
    res->get_system()->init_from_reader(_system->as_reader());
}

void Cluster::system_activate(SystemActivateParams::RootReader *args, SystemActivateResult::RootBuilder *res)
{
    res->set_code(SystemActivateResultCode::SUCCESS);
    if (_system->get_state() != SystemState::INIT) {
        return;
    }

    _system->set_estore_shard_count(args->get_estore_shard_count());
    _system->set_state(SystemState::ONLINE);

    PT_INFO(CONTROL, "System activated. State is now ONLINE.");

    initialize_all_dnodes();

    _mio->activate();

    // potentially activate all nodes
    IMDB_ITER_CHILDREN(_system, cnode, CNode, {
        calc_cnode_state(cnode);
    });
}

void Cluster::system_redist(SystemRedistParams::RootReader *args, SystemRedistResult::RootBuilder *res)
{
    //TODO: enlarge section count and redistribute the data
    initialize_all_dnodes();
    res->set_code(SystemRedistResultCode::SUCCESS);
}

EnvObj *Cluster::create_env(BaseNode *node, P::byte silo_count, uint16_t port)
{
    EnvObj *env = _tree->create<EnvObj>(P::GUID::create(), node);

    env->set_state(EnvState::INIT);
    env->set_silo_count(silo_count);
    env->set_port(port);
    env->set_connected(false);
    env->set_id(_system->allocate_env_id());
    return env;
}

BaseTreeObject *Cluster::create_module(EnvObj *env, ModuleId module_id, SiloId silo_id)
{
    BaseTreeObject *object = ModuleRegistry::get(module_id)->create_control_object(_tree, env);
    BaseModuleLogic *module = (BaseModuleLogic*) object;
    module->get_base_module()->set_state(ModuleState::OFFLINE);
    module->get_base_module()->set_silo_id(silo_id);
    return object;
}

void Cluster::calc_cnode_state(CNode *cnode)
{
    if (cnode->get_base_node()->get_enabled()) {
        // unlike D-Nodes that transition from INIT to ACTIVE upon system_redist command,
        // the C-Node automatically transitions to ACTIVE from INIT if it's enabled
        // and the system isn't in INIT.
        if ((cnode->get_base_node()->get_state() == NodeState::INACTIVE ||
             cnode->get_base_node()->get_state() == NodeState::INIT)
            && _system->get_state() != SystemState::INIT)
            cnode_activate(cnode);
    } else {
        if (cnode->get_base_node()->get_state() == NodeState::ACTIVE)
            cnode_deactivate(cnode);
    }
}

void Cluster::calc_dnode_state(DNode *dnode)
{
    if (dnode->get_base_node()->get_enabled()) {
        if (dnode->get_base_node()->get_state() == NodeState::INACTIVE && _system->get_state() != SystemState::INIT)
            dnode_activate(dnode);
    } else {
        if (dnode->get_base_node()->get_state() == NodeState::ACTIVE)
            dnode_deactivate(dnode);
    }
}

void Cluster::env_activate(EnvObj *env)
{
    IMDB_ITER_MODULES(env, module, {
        module->activate();
        char guid_string[P::GUID::STRING_SIZE];
        module->get_guid().to_string(guid_string);
        PT_INFO(CONTROL, "Activated module=%s module_id=%hhu env_id=%d", guid_string, module->get_module_id(), env->get_id());
    });
    env->set_state(EnvState::ACTIVE);
}

void Cluster::env_start(EnvObj *env)
{
    char guid_string[P::GUID::STRING_SIZE];
    env->get_guid().to_string(guid_string);

    P::PModuleAgentClient client;
    client.init();

    P::EnvStartParams::RootBuilder *params = client.alloc_env_start();
    params->set_env_guid(env->get_guid());
    env->generate_config(params->get_config(), params->get_config_count());
    RpcGuard<P::EnvStartResult::RootReader> result;
    CNode *cnode = env->get_parent<CNode>();
    PModuleObj *module = cnode->get_platform_module();
    if (client.env_start_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
    P::EnvStartResultCode code = result->get_code();
    if (code != P::EnvStartResultCode::SUCCESS)
        PT_ERROR(CONTROL, "Error starting env=%s with code=%hhd", guid_string, code);
}

void Cluster::env_stop(EnvObj *env)
{
    char guid_string[P::GUID::STRING_SIZE];
    env->get_guid().to_string(guid_string);

    P::PModuleAgentClient client;
    client.init();

    P::EnvStopParams::RootBuilder *params = client.alloc_env_stop();
    params->set_env_guid(env->get_guid());
    CNode *cnode = env->get_parent<CNode>();
    PModuleObj *module = cnode->get_platform_module();
    RpcGuard<P::EnvStopResult::RootReader> result;
    if (client.env_stop_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
    P::EnvStopResultCode code = result->get_code();
    if (code != P::EnvStopResultCode::SUCCESS)
        PT_ERROR(CONTROL, "Error stoping env=%s with code=%hhd", guid_string, code);
}

void Cluster::connect_all_cnodes_to_node(BaseNode *node)
{
    IMDB_ITER_CHILDREN(_system, cnode, CNode, {
        if (cnode == node || cnode->get_base_node()->get_state() != NodeState::ACTIVE)
            continue;
        IMDB_ITER_CHILDREN(cnode, other_env, EnvObj, {
            if (other_env->is_platform())
                continue;
            IMDB_ITER_CHILDREN(node, env, EnvObj, {
                if (env->is_platform())
                    continue;
                connect_env_to_env(env, other_env);
                connect_env_to_env(other_env, env);
            });
        });
    });
}

void Cluster::connect_all_dnodes_to_node(BaseNode *node)
{
    IMDB_ITER_CHILDREN(_system, dbox, DBox, {
        IMDB_ITER_CHILDREN(dbox, dnode, DNode, {
            IMDB_ITER_CHILDREN(dnode, other_env, EnvObj, {
                if (other_env->is_platform() || dnode->get_base_node()->get_state() != NodeState::ACTIVE)
                    continue;
                IMDB_ITER_CHILDREN(node, env, EnvObj, {
                    if (env->is_platform())
                        continue;
                    connect_env_to_env(env, other_env);
                    connect_env_to_env(other_env, env);
                });
            });
        });
    });
}

void Cluster::cnode_activate(CNode *cnode)
{
    // 1. start envs on this node.
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        if (env->is_platform())
            continue;
        env_start(env);
        connect_env(env);
    });

    // 2. interconnect the envs on this node with the rest of the envs in the system.
    connect_all_cnodes_to_node(cnode);
    connect_all_dnodes_to_node(cnode);

    // 3. activate the envs.
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        env_activate(env);
    });

    char guid_string[P::GUID::STRING_SIZE];
    cnode->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Activated node=%s", guid_string);

    cnode->get_base_node()->set_state(NodeState::ACTIVE);
}

void Cluster::node_deactivate(BaseNode *node)
{
    IMDB_ITER_CHILDREN(node, env, EnvObj, {
        if (env->is_platform())
            continue;
        env_stop(env);
    });

    char guid_string[P::GUID::STRING_SIZE];
    node->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Deactivated node=%s", guid_string);

    node->get_base_node()->set_state(NodeState::INACTIVE);
}

void Cluster::cnode_deactivate(CNode *cnode)
{
    node_deactivate(cnode);
}

void Cluster::cnode_add(CNodeAddParams::RootReader *args, CNodeAddResult::RootBuilder *res)
{
    NodeAddress::Reader address;
    LOOP(args->get_addresses_count(), i) {
        args->get_addresses(&address, i);
        if (address_already_exists(address.get_host())) {
            res->set_code(CNodeAddResultCode::ADDRESS_ALREADY_EXISTS);
            return;
        }
    }

    // create the CNode
    bool already_exists;
    CNode *cnode = _tree->get_or_create<CNode>(args->get_guid(), &already_exists, _system);
    if (cnode == nullptr) {
        res->set_code(CNodeAddResultCode::NO_MEM);
        return;
    }
    if (already_exists) {
        res->set_code(CNodeAddResultCode::GUID_ALREADY_EXISTS);
        return;
    }

    // init the CNode's properties
    LOOP(cnode->get_base_node()->get_addresses_count(), i) {
        args->get_addresses(&address, i);
        cnode->get_base_node()->get_addresses(i)->init_from_reader(&address);
    }
    cnode->get_base_node()->set_enabled(false);
    cnode->get_base_node()->set_state(NodeState::INIT);
    sprintf(cnode->get_base_proto()->get_name(), "cnode-%03d", _system->allocate_cnode_id());

    // create the child data EnvObjs
    EnvConfig::Reader env_config;
    SiloConfig::Reader silo_config;
    LOOP(args->get_env_count(), env_index) {
        args->get_env_configs(&env_config, env_index);
        EnvObj *env = create_env(cnode, env_config.get_silo_count(), env_config.get_port());
        LOOP(env_config.get_silo_count(), silo_index) {
            env_config.get_silo_configs(&silo_config, silo_index);
            env->get_silos(silo_index)->set_affinity(silo_config.get_affinity());
            LOOP(silo_config.get_modules_enabled_count(), module_index) {
                if (*silo_config.get_modules_enabled(module_index))
                    create_module(env, (ModuleId) module_index, silo_index);
            }
        }
    }

    connect_env(cnode->get_platform_env());

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

    cnode->get_base_node()->set_enabled(args->get_enabled());
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
    if (cnode->get_base_node()->get_enabled()) {
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

void Cluster::dbox_add(DBoxAddParams::RootReader *args, DBoxAddResult::RootBuilder *res)
{
    DNodeConfig::Reader dnode_config;
    NodeAddress::Reader address;
    LOOP(args->get_dnodes_config_count(), i) {
        args->get_dnodes_config(&dnode_config, i);
        LOOP(dnode_config.get_addresses_count(), j) {
            dnode_config.get_addresses(&address, i);
            if (address_already_exists(address.get_host())) {
                res->set_code(DBoxAddResultCode::ADDRESS_ALREADY_EXISTS);
                return;
            }
        }
    }

    // create the DBox
    bool already_exists;
    DBox *dbox = _tree->get_or_create<DBox>(args->get_guid(), &already_exists, _system);
    if (dbox == nullptr) {
        res->set_code(DBoxAddResultCode::NO_MEM);
        return;
    }
    if (already_exists) {
        res->set_code(DBoxAddResultCode::GUID_ALREADY_EXISTS);
        return;
    }

    // init the DBox's properties
    sprintf(dbox->get_base_proto()->get_name(), "dbox-%03d", _system->allocate_dbox_id());

    // create the DNodes
    LOOP(args->get_dnodes_config_count(), i) {
        args->get_dnodes_config(&dnode_config, i);
        DNode *dnode = _tree->create<DNode>(dnode_config.get_guid(), dbox);
        ASSERT_NOT_NULL(dnode);
        sprintf(dnode->get_base_proto()->get_name(), "dnode-%03d", _system->allocate_dnode_id());

        LOOP(dnode_config.get_addresses_count(), j) {
            dnode_config.get_addresses(&address, j);
            dnode->get_base_node()->get_addresses(j)->init_from_reader(&address);
        }
        dnode->get_base_node()->set_state(NodeState::INIT);
        dnode->get_base_node()->set_enabled(false);

        LOOP(P::DNODE_NVRAM_COUNT, j) {
            NVRAM *nvram = _tree->create<NVRAM>(P::GUID::create(), dnode);
            nvram->set_size(600 * UNIT_GiB);  // TODO: get size from the DNode
        }

        // create the child EnvObjs
        EnvConfig::Reader env_config;
        SiloConfig::Reader silo_config;
        LOOP(dnode_config.get_env_count(), env_index) {
            dnode_config.get_env_configs(&env_config, env_index);
            EnvObj *env = create_env(dnode, env_config.get_silo_count(), env_config.get_port());
            LOOP(env_config.get_silo_count(), silo_index) {
                env_config.get_silo_configs(&silo_config, silo_index);
                env->get_silos(silo_index)->set_affinity(silo_config.get_affinity());
                LOOP(silo_config.get_modules_enabled_count(), module_index) {
                    if (*silo_config.get_modules_enabled(module_index))
                        create_module(env, (ModuleId) module_index, silo_index);
                }
            }
        }

        connect_env(dnode->get_platform_env());
    }

    char guid_string[P::GUID::STRING_SIZE];
    args->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Added dbox=%s", guid_string);

    res->set_code(DBoxAddResultCode::SUCCESS);
}

void Cluster::dbox_get(DBoxGetParams::RootReader *args, DBoxGetResult::RootBuilder *res)
{
    DBox *dbox = _tree->get<DBox>(args->get_guid());
    if (dbox == nullptr) {
        res->set_code(DBoxGetResultCode::NOT_FOUND);
        return;
    }
    res->get_dbox()->init_from_reader(dbox->as_reader());
    int i = 0;
    IMDB_ITER_CHILDREN(dbox, dnode, DNode, {
        res->get_dnodes(i++)->init_from_reader(dnode->as_reader());
    });
    res->set_code(DBoxGetResultCode::SUCCESS);
}

void Cluster::dnode_modify(DNodeModifyParams::RootReader *args, DNodeModifyResult::RootBuilder *res)
{
    DNode *dnode = _tree->get<DNode>(args->get_guid());
    if (dnode == nullptr) {
        res->set_code(DNodeModifyResultCode::NOT_FOUND);
        return;
    }

    char guid_string[P::GUID::STRING_SIZE];
    args->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Modified dnode=%s: enabled=%c", guid_string, args->get_enabled());

    dnode->get_base_node()->set_enabled(args->get_enabled());

    calc_dnode_state(dnode);

    res->set_code(DNodeModifyResultCode::SUCCESS);
}

void Cluster::initialize_all_dnodes()
{
    IMDB_ITER_CHILDREN(_system, dbox, DBox, {
        IMDB_ITER_CHILDREN(dbox, dnode, DNode, {
            if (dnode->get_base_node()->get_state() == NodeState::INIT && dnode->get_base_node()->get_enabled())
                dnode_initialize(dnode);
        });
    });
}

void Cluster::dnode_initialize(DNode *dnode)
{
    //TODO: query the dnode platform for the NVRAM size and version
    dnode_activate(dnode);
}

void Cluster::dnode_activate(DNode *dnode)
{
    // 1. start envs on this node.
    IMDB_ITER_CHILDREN(dnode, env, EnvObj, {
        if (env->is_platform())
            continue;
        env_start(env);
        connect_env(env);
    });

    // 2. interconnect the envs on this node with the rest of the envs in the system.
    connect_all_cnodes_to_node(dnode);

    // 3. activate the envs.
    IMDB_ITER_CHILDREN(dnode, env, EnvObj, {
        env_activate(env);
    });

    IMDB_ITER_CHILDREN(dnode, nvram, NVRAM, {
        nvram_activate(nvram);
    });

    char guid_string[P::GUID::STRING_SIZE];
    dnode->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Activated node=%s", guid_string);

    dnode->get_base_node()->set_state(NodeState::ACTIVE);
}

void Cluster::dnode_deactivate(DNode *dnode)
{
    IMDB_ITER_CHILDREN(dnode, nvram, NVRAM, {
        nvram_deactivate(nvram);
    });
    node_deactivate(dnode);
}

void Cluster::nvram_activate(NVRAM *nvram)
{
    map_on_cnodes(&Cluster::connect_cnode_to_device, nvram);

    _mio->on_device_activated(nvram);

    char guid_string[P::GUID::STRING_SIZE];
    nvram->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Activated nvram=%s", guid_string);
}

void Cluster::connect_cnode_to_device(CNode *cnode, NVRAM *nvram)
{
    P::PModuleAgentClient client;
    client.init();

    PModuleObj *module = cnode->get_platform_module();
    P::ConnectDeviceParams::RootBuilder *params = client.alloc_connect_device();
    params->set_guid(nvram->get_guid());
    LOOP(params->get_dnode_addresses_count(), i)
        *(params->get_dnode_addresses(i)) = *(nvram->get_parent<DNode>()->get_base_node()->get_addresses(i));

    RpcGuard<P::ConnectDeviceResult::RootReader> result;
    if (client.connect_device_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }

    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        if (env->is_platform())
            continue;
        Cluster::connect_env_to_device(env, nvram, result->get_path());
    });
}

void Cluster::connect_env_to_device(EnvObj *env, NVRAM *nvram, char *local_path)
{
    DevAgentClient client;
    client.init();

    IMDB_ITER_CHILDREN(env, module, IModuleObj, {
        DeviceAddParams::RootBuilder *params = client.alloc_device_add();
        params->set_device_count(1);
        RemoteDeviceProto::Builder *device = params->get_devices(0);
        device->set_guid(nvram->get_guid());
        strncpy(device->get_path(), local_path, device->get_path_count());

        if (client.device_add_sync(module->get_address(), params) != P::VMsg::VMsgRes::OK) {
            PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
        }
    });
}

void Cluster::prepare_disconnect_env_from_device(EnvObj *env, NVRAM *nvram)
{
    DevAgentClient client;
    client.init();

    IMDB_ITER_CHILDREN(env, module, IModuleObj, {
        DevicePrepareRemoveParams::RootBuilder *prepare_params = client.alloc_device_prepare_remove();
        prepare_params->set_guid_count(1);
        *(prepare_params->get_guids(0)) = nvram->get_guid();
        if (client.device_prepare_remove_sync(module->get_address(), prepare_params) != P::VMsg::VMsgRes::OK) {
            PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
        }
    });
}

void Cluster::disconnect_env_from_device(EnvObj *env, NVRAM *nvram)
{
    DevAgentClient client;
    client.init();

    IMDB_ITER_CHILDREN(env, module, IModuleObj, {
        DeviceRemoveParams::RootBuilder *remove_params = client.alloc_device_remove();
        remove_params->set_guid_count(1);
        *(remove_params->get_guids(0)) = nvram->get_guid();
        if (client.device_remove_sync(module->get_address(), remove_params) != P::VMsg::VMsgRes::OK) {
            PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
        }
    });
}

void Cluster::prepare_disconnect_cnode_from_device(CNode *cnode, NVRAM *nvram)
{
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        if (env->is_platform())
            continue;
        Cluster::prepare_disconnect_env_from_device(env, nvram);
    });
}

void Cluster::disconnect_cnode_from_device(CNode *cnode, NVRAM *nvram)
{
    IMDB_ITER_CHILDREN(cnode, env, EnvObj, {
        if (env->is_platform())
            continue;
        Cluster::disconnect_env_from_device(env, nvram);
    });

    P::PModuleAgentClient client;
    client.init();

    PModuleObj *module = cnode->get_platform_module();
    P::DisconnectDeviceParams::RootBuilder *params = client.alloc_disconnect_device();
    params->set_guid(nvram->get_guid());
    RpcGuard<P::DisconnectDeviceResult::RootReader> result;
    if (client.disconnect_device_sync(module->get_address(), params, &result) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure"); //TODO: unify handling of VMsg errors
    }
}

void Cluster::nvram_deactivate(NVRAM *nvram)
{
    map_on_cnodes(&Cluster::prepare_disconnect_cnode_from_device, nvram);
    _mio->on_device_deactivated(nvram);
    map_on_cnodes(&Cluster::disconnect_cnode_from_device, nvram);

    char guid_string[P::GUID::STRING_SIZE];
    nvram->get_guid().to_string(guid_string);
    PT_INFO(CONTROL, "Deactivated nvram=%s", guid_string);
}

template <typename Func, typename Param>
class CNodeFunctor : public IRunnable {
public:
    void init(Cluster *cluster, CNode *cnode, Func func, Param param)
    {
        _cluster = cluster;
        _cnode = cnode;
        _func = func;
        _param = param;
    }

    void run()
    {
        (_cluster->*_func)(_cnode, _param);
    }

private:
    Cluster *_cluster;
    CNode *_cnode;
    Func _func;
    Param _param;
};

template <typename Func, typename Param>
void Cluster::map_on_cnodes(Func func, Param param)
{
    using Functor = CNodeFunctor<Func, Param>;
    IMDB_ITER_CHILDREN(_system, cnode, CNode, {
        if (cnode->get_base_node()->get_state() != NodeState::ACTIVE)
            continue;
        void *mem = alloca(sizeof(Functor));
        Functor *functor = new (mem) Functor;
        functor->init(this, cnode, func, param);
        P::Fiber *fiber = P::Fiber::init((P::Index)FiberGroupId::C, runner<Functor>, functor, true);
        ASSERT_NOT_NULL(fiber);
    });
    P::Fiber::join_all();
}

}
