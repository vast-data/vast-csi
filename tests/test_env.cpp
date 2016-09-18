/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>

#include "test_cluster.hpp"
#include "globals.hpp"
#include "control/cluster/cluster.rpc.client.hpp"
#include "modules/e_module_agent_server.hpp"
#include "modules/p_module_agent.rpc.client.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/utils/os.hpp"
#include "test_module.hpp"

using namespace P::VMsg;

static const EnvId LEADER_ENV_ID = 100;
static const uint16_t TEST_ENV_PORT = 4000;
static const uint16_t LEADER_PORT = 6000;

static const ModuleAddress local_dest = {
        1,  // env_id
        0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
        (uint8_t) ModuleId::P,  // module_id : 4
        0  // silo_id
};

static const ModuleAddress leader_dest = {
        LEADER_ENV_ID,  // env_id
        0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
        (uint8_t) ModuleId::P,  // module_id : 4
        0  // silo_id
};

static const ModuleAddress leader_dest_control = {
        LEADER_ENV_ID,  // env_id
        0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
        (uint8_t) ModuleId::C,  // module_id : 4
        0  // silo_id
};

static void init_func(UNUSED P::Silo *silo, UNUSED void *ctx)
{
    // Nothing to do for now. Use if/when relevant.
}

static P::EnvStartResultCode send_env_start(P::GUID env_guid, const char *config)
{
    P::PModuleAgentClient client;
    client.init();

    P::EnvStartParams::RootBuilder *env_start_params = client.alloc_env_start();
    env_start_params->set_env_guid(env_guid);
    strcpy(env_start_params->get_config(), config);
    RpcGuard<P::EnvStartResult::RootReader> env_start_reply;
    EXPECT_EQ(VMsgRes::OK, client.env_start_sync(local_dest, env_start_params, &env_start_reply));
    return env_start_reply->get_code();
}

static P::EnvStopResultCode send_env_stop(P::GUID env_guid)
{
    P::PModuleAgentClient client;
    client.init();

    P::EnvStopParams::RootBuilder *env_stop_params = client.alloc_env_stop();
    env_stop_params->set_env_guid(env_guid);
    RpcGuard<P::EnvStopResult::RootReader> env_stop_reply;
    EXPECT_EQ(VMsgRes::OK, client.env_stop_sync(local_dest, env_stop_params, &env_stop_reply));
    return env_stop_reply->get_code();
}

static P::EnvStartResultCode send_run_leader()
{
    P::PModuleAgentClient client;
    client.init();

    RpcGuard<P::EnvStartResult::RootReader> env_start_reply;
    EXPECT_EQ(VMsgRes::OK, client.run_leader_sync(local_dest, nullptr, &env_start_reply));
    return env_start_reply->get_code();
}

static Control::SystemState send_system_status()
{
    Control::ClusterClient client;
    client.init();

    Control::SystemStatusParams::RootBuilder *system_status_params = client.alloc_system_status();
    RpcGuard<Control::SystemStatusResult::RootReader> system_status_reply;
    EXPECT_EQ(VMsgRes::OK, client.system_status_sync(leader_dest_control, system_status_params, &system_status_reply));
    Control::SystemProto::Reader system_reader;
    system_status_reply->get_system(&system_reader);
    return system_reader.get_state();
}

static void send_set_local_env_id(uint16_t env_id)
{
    P::PModuleAgentClient client;
    client.init();

    P::SetLocalEnvIdParams::RootBuilder *set_local_env_id_params = client.alloc_set_local_env_id();
    P::ConnectParams::Builder *connect_params = set_local_env_id_params->get_connect_params();
    set_local_env_id_params->set_env_id(env_id);
    set_local_env_id_params->get_connect_params()->set_env_id(1);
    set_local_env_id_params->get_connect_params()->get_addresses()->set_n_addr(1);
    set_local_env_id_params->get_connect_params()->get_addresses()->get_addresses(0)->set_port(TEST_ENV_PORT);
    strcpy(set_local_env_id_params->get_connect_params()->get_addresses()->get_addresses(0)->get_host(), "127.0.0.01");

    ASSERT(MODULES_COUNT == connect_params->get_modules_count());
    LOOP(MODULES_COUNT, i) {
        *connect_params->get_modules(i) = false;
    }
    *connect_params->get_modules((P::byte)ModuleId::P) = true;
    *connect_params->get_modules((P::byte)ModuleId::E) = true;
    *connect_params->get_modules((P::byte)ModuleId::C) = true;
    *connect_params->get_modules((P::byte)ModuleId::TEST) = true;

    EXPECT_EQ(VMsgRes::OK, client.set_local_env_id_sync(leader_dest, set_local_env_id_params));
}

static void update_config_port(char *config, uint16_t port)
{
    char port_buf[6];
    sprintf(port_buf, "%d", port);
    ASSERT_EQ(4, strlen(port_buf));  // Originally, the port is 4000, so it's easiest to keep the same length.
    const char* port_str = port_buf;

    char *port_pos = strstr(config, "port: ");
    ASSERT_NOT_NULL(port_pos);
    port_pos += strlen("port: ");
    while (*port_str) {
        *port_pos++ = *port_str++;
    }
}

static void env_start_stop_start_func(UNUSED void *ctx)
{
    global_env_stop = false;

    if (P::Silo::get()->get_id() > 0) {
        return;
    }

    P::GUID env_guid;
    env_guid.init();

    char config[P::MAX_CONFIG_SIZE];
    ASSERT(P::file_to_string("tests/env_test.config", P::MAX_CONFIG_SIZE, config));
    uint16_t port = 5000;

    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(env_guid));
    update_config_port(config, port++);
    EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStartResultCode::GUID_ALREADY_EXISTS, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guid));
    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(env_guid));

    P::GUID env_guids[P::MAX_ENVS_PER_CNODE - 1];
    for (uint32_t i = 0; i < P::MAX_ENVS_PER_CNODE - 1; ++i) {
        env_guids[i].init();
        update_config_port(config, port++);
        EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(env_guids[i], config));
    }

    EXPECT_EQ(P::EnvStartResultCode::MAX_ENVS_CREATED, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guids[0]));
    update_config_port(config, port++);
    EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guid));

    for (uint32_t i = 1; i < P::MAX_ENVS_PER_CNODE - 1; ++i) {
        EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guids[i]));
    }

    global_env_stop = true;
}

static void run_leader_start_func(UNUSED void *ctx)
{
    global_env_stop = false;

    if (P::Silo::get()->get_id() > 0) {
        return;
    }

    P::GUID leader_env_guid;
    ASSERT(leader_env_guid.init_from_string(P::LEADER_ENV_GUID));

    // Run the new Leader env
    Test::create_system_guid();
    EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_run_leader());

    // Connect to the new env (to be able to send RPC's to it)
    P::ConnectParams::RootBuilder connect_params_builder;
    connect_params_builder.init();
    connect_params_builder.set_env_id(LEADER_ENV_ID);
    connect_params_builder.get_addresses()->set_n_addr(1);
    connect_params_builder.get_addresses()->get_addresses(0)->set_port(LEADER_PORT);
    strcpy(connect_params_builder.get_addresses()->get_addresses(0)->get_host(), "127.0.0.1");

    ASSERT(MODULES_COUNT == connect_params_builder.get_modules_count());
    LOOP(MODULES_COUNT, i) {
        *connect_params_builder.get_modules(i) = false;
    }
    *connect_params_builder.get_modules((P::byte)ModuleId::P) = true;
    *connect_params_builder.get_modules((P::byte)ModuleId::E) = true;
    *connect_params_builder.get_modules((P::byte)ModuleId::C) = true;
    *connect_params_builder.get_modules((P::byte)ModuleId::TEST) = true;

    P::ConnectParams::Reader connect_params_reader;
    connect_params_reader.init_from_root(connect_params_builder.as_reader());
    P::EModuleAgentServerImpl::do_connect(&connect_params_reader);

    // Set local env ID on the new env (and tell it to connect to this env)
    send_set_local_env_id(LEADER_ENV_ID);

    // Communicate with the new env
    EXPECT_EQ(Control::SystemState::INIT, send_system_status());
    EXPECT_EQ(P::EnvStartResultCode::GUID_ALREADY_EXISTS, send_run_leader());
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(leader_env_guid));
    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(leader_env_guid));

    global_env_stop = true;
}

TEST(TestEnv, env_start_stop)
{
    TestModule::set_init_func(init_func, nullptr);
    TestModule::set_start_func(env_start_stop_start_func, nullptr);

    P::Env::get()->run("dist/env" /* binary_path */, "tests/env_test.config");
    EXPECT_TRUE(TestModule::is_init()) << "test module expected to be init";
    EXPECT_TRUE(TestModule::is_started()) << "test module expected to be started";
}

TEST(TestEnv, run_leader)
{
    TestModule::set_init_func(init_func, nullptr);
    TestModule::set_start_func(run_leader_start_func, nullptr);

    P::Env::get()->run("dist/env" /* binary_path */, "tests/env_test.config");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
