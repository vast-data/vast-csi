/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "test_cluster.hpp"
#include "globals.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/vmsg/vmsg.hpp"
#include "test_module.hpp"
#include "control/cluster/cluster.rpc.client.hpp"

using namespace P;
using namespace Control;

static const VMsg::ModuleAddress dest = {
    1,  // env_id
    0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
    (uint8_t) ModuleId::C,  // module_id : 4
    0  // silo_id
};

static void init_func(P::Silo *silo, void *ctx)
{
    VMsg::VMsg *vmsg = P::Env::get()->get_vmsg();
    vmsg->add_module_pair(ModuleId::TEST, ModuleId::C, VMsg::TransportType::RDMA);
}

static void system_init(ClusterClient *client)
{
    SystemInitParams::RootBuilder *init_params = client->alloc_system_init();
    SystemInitResult::RootReader *init_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client->system_init_sync(dest, init_params, &init_result));
    ASSERT_EQ(init_result->get_code(), SystemInitResultCode::SUCCESS);
    client->free_system_init(init_result);
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

static void system_init_start_func(void *ctx)
{
    ClusterClient client;
    client.init();

    ASSERT_EQ(get_system_state(&client), SystemState::INIT);
    system_init(&client);
    ASSERT_EQ(get_system_state(&client), SystemState::ONLINE);

    env_stop = true;
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

    CNodeAddParams::RootBuilder *cnode_add_params = client.alloc_cnode_add();
    cnode_add_params->set_guid(cnode_guid);
    cnode_add_params->set_env_count(0);
    LOOP(2, i)
        strcpy(cnode_add_params->get_addresses(i)->get_host(), "127.0.0.1");
    CNodeAddResult::RootReader *cnode_add_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client.cnode_add_sync(dest, cnode_add_params, &cnode_add_result));
    ASSERT_EQ(cnode_add_result->get_code(), CNodeAddResultCode::SUCCESS);

    CNodeGetResult::RootReader *cnode_get_result;
    get_cnode(&client, cnode_guid, &cnode_get_result);
    CNodeProto::Reader cnode;
    cnode_get_result->get_cnode(&cnode);
    ASSERT_EQ(cnode.get_state(), CNodeState::INACTIVE);
    ASSERT_FALSE(cnode.get_enabled());
    client.free_cnode_get(cnode_get_result);

    CNodeModifyParams::RootBuilder *cnode_modify_params = client.alloc_cnode_modify();
    cnode_modify_params->set_guid(cnode_guid);
    cnode_modify_params->set_enabled(true);
    CNodeModifyResult::RootReader *cnode_modify_result;
    ASSERT_EQ(VMsg::VMsgRes::OK, client.cnode_modify_sync(dest, cnode_modify_params, &cnode_modify_result));
    ASSERT_EQ(cnode_modify_result->get_code(), CNodeModifyResultCode::SUCCESS);

    get_cnode(&client, cnode_guid, &cnode_get_result);
    cnode_get_result->get_cnode(&cnode);
    ASSERT_EQ(cnode.get_state(), CNodeState::INACTIVE);
    ASSERT_TRUE(cnode.get_enabled());
    client.free_cnode_get(cnode_get_result);

    system_init(&client);

    get_cnode(&client, cnode_guid, &cnode_get_result);
    cnode_get_result->get_cnode(&cnode);
    ASSERT_EQ(cnode.get_state(), CNodeState::ACTIVE);
    ASSERT_TRUE(cnode.get_enabled());
    client.free_cnode_get(cnode_get_result);

    env_stop = true;
}

void cluster_test(StartFunc start_func)
{
    Test::create_system_guid();

    TestModule::set_init_func(init_func, nullptr);
    TestModule::set_start_func(start_func, nullptr);

    env_stop = false;
    P::Env::get()->run("dist/env", "tests/cluster_test.config");
}

TEST(TestEnv, system_init)
{
    cluster_test(system_init_start_func);
}

TEST(TestEnv, cnode_activation)
{
    pid_t platform_pid = ::Test::run_env("tests/platform.config");
    cluster_test(cnode_activation_start_func);
    kill(platform_pid, 9);
}

#include "globals.hpp"

int main(int argc, char **argv) {
    debugging = true;
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
