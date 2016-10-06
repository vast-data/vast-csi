/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "test_cluster.hpp"
#include "globals.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/vmsg/vmsg.hpp"
#include "test_module.hpp"
#include "control/imdb/node.hpp"
#include "control/cluster/cluster.rpc.client.hpp"
#include "control/cluster/component.hpp"

using namespace P;
using namespace Control;

static const VMsg::ModuleAddress dest = {
    LEADER_ENV_ID,  // env_id
    0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
    (uint8_t) ModuleId::C,  // module_id : 4
    0  // silo_id
};

static void system_activate(ClusterClient *client)
{
    SystemActivateParams::RootBuilder *activate_params = client->alloc_system_activate();
    activate_params->set_shard_count(1024);
    SystemActivateResult::RootReader *activate_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client->system_activate_sync(dest, activate_params, &activate_result));
    ASSERT_EQ(activate_result->get_code(), SystemActivateResultCode::SUCCESS);
    client->free_system_activate(activate_result);
}

static SystemState get_system_state(ClusterClient *client)
{
    SystemStatusParams::RootBuilder *status_params = client->alloc_system_status();
    SystemStatusResult::RootReader *status_result;
    EXPECT_EQ(VMsg::VMsgRes::OK, client->system_status_sync(dest, status_params, &status_result));
    SystemProto::Reader system;
    status_result->get_system(&system);
    auto result = system.get_state();
    client->free_system_status(status_result);
    return result;
}

static void system_activate_start_func(void *ctx)
{
    ClusterClient client;
    client.init();

    ASSERT_EQ(get_system_state(&client), SystemState::INIT);
    system_activate(&client);
    ASSERT_EQ(get_system_state(&client), SystemState::ONLINE);

    env_stop = true;
}

static void add_cnode(ClusterClient *client, GUID guid, uint16_t platform_port, uint16_t data_port)
{
    CNodeAddParams::RootBuilder *cnode_add_params = client->alloc_cnode_add();
    cnode_add_params->set_guid(guid);
    cnode_add_params->set_env_count(2);
    LOOP(cnode_add_params->get_addresses_count(), i)
        strcpy(cnode_add_params->get_addresses(i)->get_host(), LOCALHOST);

    // platform env
    EnvConfig::Builder *env_conf = cnode_add_params->get_env_configs(0);
    env_conf->set_port(platform_port);
    env_conf->set_silo_count(1);
    SiloConfig::Builder *silo_conf = env_conf->get_silo_configs(0);
    silo_conf->set_affinity(P::Silo::NO_AFFINITY);
    LOOP(ModuleId::COUNT, i)
        *(silo_conf->get_modules_enabled(i)) = false;
    *(silo_conf->get_modules_enabled((uint16_t)ModuleId::E)) = true;
    *(silo_conf->get_modules_enabled((uint16_t)ModuleId::P)) = true;

    // data env
    env_conf = cnode_add_params->get_env_configs(1);
    env_conf->set_port(data_port);
    env_conf->set_silo_count(1);
    silo_conf = env_conf->get_silo_configs(0);
    silo_conf->set_affinity(0);
    LOOP(ModuleId::COUNT, i)
        *(silo_conf->get_modules_enabled(i)) = false;
    *(silo_conf->get_modules_enabled((uint16_t)ModuleId::E)) = true;

    CNodeAddResult::RootReader *cnode_add_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client->cnode_add_sync(dest, cnode_add_params, &cnode_add_result));
    ASSERT_EQ(cnode_add_result->get_code(), CNodeAddResultCode::SUCCESS);
    client->free_cnode_add(cnode_add_result);
}

static void add_dbox(ClusterClient *client, GUID guid, GUID dnode1_guid, GUID dnode2_guid,
                     uint16_t platform_base_port, uint16_t data_base_port)
{
    DBoxAddParams::RootBuilder *dbox_add_params = client->alloc_dbox_add();
    dbox_add_params->set_guid(guid);
    LOOP(dbox_add_params->get_dnodes_config_count(), i) {
        DNodeConfig::Builder *dnode_config = dbox_add_params->get_dnodes_config(i);
        dnode_config->set_env_count(2);
        dnode_config->set_guid(i == 0 ? dnode1_guid : dnode2_guid);
        LOOP(dnode_config->get_addresses_count(), j)
            strcpy(dnode_config->get_addresses(j)->get_host(), LOCALHOST);

        // platform env
        EnvConfig::Builder *env_conf = dnode_config->get_env_configs(0);
        env_conf->set_port(platform_base_port + i);
        env_conf->set_silo_count(1);
        SiloConfig::Builder *silo_conf = env_conf->get_silo_configs(0);
        silo_conf->set_affinity(P::Silo::NO_AFFINITY);
        LOOP(ModuleId::COUNT, i)
            *(silo_conf->get_modules_enabled(i)) = false;
        *(silo_conf->get_modules_enabled((uint16_t)ModuleId::E)) = true;
        *(silo_conf->get_modules_enabled((uint16_t)ModuleId::P)) = true;

        // data env
        env_conf = dnode_config->get_env_configs(1);
        env_conf->set_port(data_base_port + i);
        env_conf->set_silo_count(1);
        silo_conf = env_conf->get_silo_configs(0);
        silo_conf->set_affinity(0);
        LOOP(ModuleId::COUNT, i)
            *(silo_conf->get_modules_enabled(i)) = false;
        *(silo_conf->get_modules_enabled((uint16_t)ModuleId::E)) = true;
    }

    DBoxAddResult::RootReader *dbox_add_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client->dbox_add_sync(dest, dbox_add_params, &dbox_add_result));
    ASSERT_EQ(dbox_add_result->get_code(), DBoxAddResultCode::SUCCESS);
    client->free_dbox_add(dbox_add_result);
}

static void set_dnode_enabled(ClusterClient *client, GUID guid, bool enabled)
{
    DNodeModifyParams::RootBuilder *dnode_modify_params = client->alloc_dnode_modify();
    dnode_modify_params->set_guid(guid);
    dnode_modify_params->set_enabled(enabled);
    DNodeModifyResult::RootReader *dnode_modify_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client->dnode_modify_sync(dest, dnode_modify_params, &dnode_modify_result));
    ASSERT_EQ(dnode_modify_result->get_code(), DNodeModifyResultCode::SUCCESS);
    client->free_dnode_modify(dnode_modify_result);
}

static void set_cnode_enabled(ClusterClient *client, GUID guid, bool enabled)
{
    CNodeModifyParams::RootBuilder *cnode_modify_params = client->alloc_cnode_modify();
    cnode_modify_params->set_guid(guid);
    cnode_modify_params->set_enabled(enabled);
    CNodeModifyResult::RootReader *cnode_modify_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client->cnode_modify_sync(dest, cnode_modify_params, &cnode_modify_result));
    ASSERT_EQ(cnode_modify_result->get_code(), CNodeModifyResultCode::SUCCESS);
    client->free_cnode_modify(cnode_modify_result);
}

static void get_cnode(ClusterClient *client, GUID guid, CNodeGetResult::RootReader **cnode_get_result)
{
    CNodeGetParams::RootBuilder *cnode_get_params = client->alloc_cnode_get();
    cnode_get_params->set_guid(guid);
    ASSERT_EQ(VMsg::VMsgRes::OK, client->cnode_get_sync(dest, cnode_get_params, cnode_get_result));
    ASSERT_EQ((*cnode_get_result)->get_code(), CNodeGetResultCode::SUCCESS);
}

static void cnode_activation_start_func(void *ctx)
{
    ClusterClient client;
    client.init();

    GUID cnode_guid = GUID::create();
    add_cnode(&client, cnode_guid, P::PLATFORM_ENV_PORT, 6001);

    CNodeGetResult::RootReader *cnode_get_result;
    get_cnode(&client, cnode_guid, &cnode_get_result);
    CNodeProto::Reader cnode;
    BaseNodeProto::Reader node;
    cnode_get_result->get_cnode(&cnode);
    cnode.get_base_node_proto(&node);
    ASSERT_EQ(node.get_state(), NodeState::INIT);
    ASSERT_FALSE(node.get_enabled());
    client.free_cnode_get(cnode_get_result);

    set_cnode_enabled(&client, cnode_guid, true);

    get_cnode(&client, cnode_guid, &cnode_get_result);
    cnode_get_result->get_cnode(&cnode);
    cnode.get_base_node_proto(&node);
    ASSERT_EQ(node.get_state(), NodeState::INIT);
    ASSERT_TRUE(node.get_enabled());
    client.free_cnode_get(cnode_get_result);

    system_activate(&client);

    get_cnode(&client, cnode_guid, &cnode_get_result);
    cnode_get_result->get_cnode(&cnode);
    cnode.get_base_node_proto(&node);
    ASSERT_EQ(node.get_state(), NodeState::ACTIVE);
    ASSERT_TRUE(node.get_enabled());
    client.free_cnode_get(cnode_get_result);

    set_cnode_enabled(&client, cnode_guid, false);

    get_cnode(&client, cnode_guid, &cnode_get_result);
    cnode_get_result->get_cnode(&cnode);
    cnode.get_base_node_proto(&node);
    ASSERT_EQ(node.get_state(), NodeState::INACTIVE);
    ASSERT_FALSE(node.get_enabled());
    client.free_cnode_get(cnode_get_result);

    env_stop = true;
}

static void get_dbox(ClusterClient *client, GUID guid, DBoxGetResult::RootReader **dbox_get_result)
{
    DBoxGetParams::RootBuilder *dbox_get_params = client->alloc_dbox_get();
    dbox_get_params->set_guid(guid);
    ASSERT_EQ(VMsg::VMsgRes::OK, client->dbox_get_sync(dest, dbox_get_params, dbox_get_result));
    ASSERT_EQ((*dbox_get_result)->get_code(), DBoxGetResultCode::SUCCESS);
}

static void dbox_activation_start_func(void *ctx)
{
    ClusterClient client;
    client.init();

    GUID dbox_guid = GUID::create();
    GUID dnode1_guid = GUID::create();
    GUID dnode2_guid = GUID::create();

    add_dbox(&client, dbox_guid, dnode1_guid, dnode2_guid, 5000, 6000);

    DBoxGetResult::RootReader *dbox_get_result;
    get_dbox(&client, dbox_guid, &dbox_get_result);
    DNodeProto::Reader dnode;
    BaseNodeProto::Reader node;
    LOOP(dbox_get_result->get_dnodes_count(), i) {
        dbox_get_result->get_dnodes(&dnode, i);
        dnode.get_base_node_proto(&node);
        ASSERT_EQ(node.get_state(), NodeState::INIT);
    }
    client.free_dbox_get(dbox_get_result);

    set_dnode_enabled(&client, dnode1_guid, true);
    set_dnode_enabled(&client, dnode2_guid, true);

    get_dbox(&client, dbox_guid, &dbox_get_result);
    LOOP(dbox_get_result->get_dnodes_count(), i) {
        dbox_get_result->get_dnodes(&dnode, i);
        dnode.get_base_node_proto(&node);
        ASSERT_EQ(node.get_state(), NodeState::INIT);
    }
    client.free_dbox_get(dbox_get_result);

    system_activate(&client);

    get_dbox(&client, dbox_guid, &dbox_get_result);
    LOOP(dbox_get_result->get_dnodes_count(), i) {
        dbox_get_result->get_dnodes(&dnode, i);
        dnode.get_base_node_proto(&node);
        ASSERT_EQ(node.get_state(), NodeState::ACTIVE);
    }
    client.free_dbox_get(dbox_get_result);

    set_dnode_enabled(&client, dnode1_guid, false);
    set_dnode_enabled(&client, dnode2_guid, false);

    env_stop = true;
}

static void full_cluster_start_func(void *ctx)
{
    ClusterClient client;
    client.init();

    GUID cnode1_guid = GUID::create();
    GUID cnode2_guid = GUID::create();

    LOOP(2, i) {
        GUID cnode_guid = i == 0 ? cnode1_guid : cnode2_guid;
        add_cnode(&client, cnode_guid, P::PLATFORM_ENV_PORT + i, 6000 + i);
        set_cnode_enabled(&client, cnode_guid, true);
    }

    GUID dbox_guid = GUID::create();
    GUID dnode1_guid = GUID::create();
    GUID dnode2_guid = GUID::create();

    add_dbox(&client, dbox_guid, dnode1_guid, dnode2_guid, 5000, 7000);

    set_dnode_enabled(&client, dnode1_guid, true);
    set_dnode_enabled(&client, dnode2_guid, true);

    system_activate(&client);

    set_dnode_enabled(&client, dnode1_guid, false);
    set_dnode_enabled(&client, dnode2_guid, false);
    set_cnode_enabled(&client, cnode1_guid, false);
    set_cnode_enabled(&client, cnode2_guid, false);

    env_stop = true;
}


void cluster_test(StartFunc start_func)
{
    ::Test::create_system_guid();

    TestModule::set_start_func(start_func, nullptr);

    env_stop = false;
    P::Env::get()->run("dist/env", "tests/cluster_test.config");
}

TEST(Cluster, system_activate)
{
    cluster_test(system_activate_start_func);
}

TEST(Cluster, cnode_activation)
{
    ::Test::EnvProcess platform("tests/platform1.config");
    cluster_test(cnode_activation_start_func);
}

TEST(Cluster, dbox_activation)
{
    ::Test::EnvProcess dplatform1("tests/dplatform1.config");
    ::Test::EnvProcess dplatform2("tests/dplatform2.config");
    cluster_test(dbox_activation_start_func);
}

TEST(Cluster, full_cluster)
{
    ::Test::EnvProcess platform1("tests/platform1.config");
    ::Test::EnvProcess platform2("tests/platform2.config");
    ::Test::EnvProcess dplatform1("tests/dplatform1.config");
    ::Test::EnvProcess dplatform2("tests/dplatform2.config");
    cluster_test(full_cluster_start_func);
}

#include "globals.hpp"

int main(int argc, char **argv) {
    debugging = true;
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
