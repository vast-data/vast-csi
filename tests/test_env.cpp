/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>

#include "globals.hpp"
#include "modules/p_module_agent.rpc.client.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/utils/os.hpp"
#include "test_module.hpp"

using namespace P::VMsg;

static const ModuleGUID dest = {
        0,  // env_id
        0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
        (uint8_t) ModuleId::P,  // module_id : 4
        0  // silo_id
};

static void init_func(P::Silo *silo, void *ctx)
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
    P::EnvStartResult::RootReader *env_start_reply;
    EXPECT_EQ(VMsgRes::OK, client.env_start_sync(dest, env_start_params, &env_start_reply));
    P::EnvStartResultCode res = env_start_reply->get_code();
    client.free_env_start(env_start_reply);
    return res;
}

static P::EnvStopResultCode send_env_stop(P::GUID env_guid)
{
    P::PModuleAgentClient client;
    client.init();

    P::EnvStopParams::RootBuilder *env_stop_params = client.alloc_env_stop();
    env_stop_params->set_env_guid(env_guid);
    P::EnvStopResult::RootReader *env_stop_reply;
    EXPECT_EQ(VMsgRes::OK, client.env_stop_sync(dest, env_stop_params, &env_stop_reply));
    P::EnvStopResultCode res = env_stop_reply->get_code();
    client.free_env_stop(env_stop_reply);
    return res;
}

static void send_set_local_env_id(uint16_t env_id)
{
    P::PModuleAgentClient client;
    client.init();

    P::SetLocalEnvIdParams::RootBuilder *set_local_env_id_params = client.alloc_set_local_env_id();
    set_local_env_id_params->set_env_id(env_id);
    P::VProto::Empty::RootReader *set_local_env_id_reply;
    EXPECT_EQ(VMsgRes::OK, client.set_local_env_id_sync(dest, set_local_env_id_params, &set_local_env_id_reply));
    client.free_set_local_env_id(set_local_env_id_reply);
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

static void env_start_stop_start_func(void *ctx)
{
    env_stop = false;

    if (P::Silo::get()->get_id() > 0) {
        return;
    }

    VMsg *vmsg = P::Env::get()->get_vmsg();
    vmsg->add_module_pair(ModuleId::TEST, ModuleId::P, TransportType::RDMA);

    P::GUID env_guid;
    env_guid.init();

    char config[2048];
    ASSERT(P::file_to_string("tests/env_test.config", 2048, config));
    uint16_t port = 5000;

    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(env_guid));
    update_config_port(config, port++);
    EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStartResultCode::GUID_ALREADY_EXISTS, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guid));
    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(env_guid));

    P::GUID env_guids[P::MAX_ENVS_PER_CNODE - 1];
    for (int i = 0; i < P::MAX_ENVS_PER_CNODE - 1; ++i) {
        env_guids[i].init();
        update_config_port(config, port++);
        EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(env_guids[i], config));
    }

    EXPECT_EQ(P::EnvStartResultCode::MAX_ENVS_CREATED, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guids[0]));
    update_config_port(config, port++);
    EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(env_guid, config));
    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guid));

    for (int i = 1; i < P::MAX_ENVS_PER_CNODE - 1; ++i) {
        EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(env_guids[i]));
    }

    env_stop = true;
}

// TODO: testing set_local_env_id is problematic, because of its effect on vmsg. So:
// 1) this should probably be the last test.
// 2) better remove it and test it as part of an integration test, i.e. send to other envs.
static void set_local_env_id_start_func(void *ctx)
{
    env_stop = false;

    if (P::Silo::get()->get_id() > 0) {
        return;
    }

    VMsg *vmsg = P::Env::get()->get_vmsg();
    vmsg->add_module_pair(ModuleId::TEST, ModuleId::P, TransportType::RDMA);

    EXPECT_EQ(0, vmsg->get_local_env_id());
    send_set_local_env_id(123);
    EXPECT_EQ(123, vmsg->get_local_env_id());

    env_stop = true;
}

TEST(TestEnv, env_start_stop)
{
    TestModule::set_init_func(init_func, nullptr);
    TestModule::set_start_func(env_start_stop_start_func, nullptr);

    P::Env::get()->run("dist/env" /* binary_path */, "tests/env_test.config");
    EXPECT_TRUE(TestModule::is_init()) << "test module expected to be init";
    EXPECT_TRUE(TestModule::is_started()) << "test module expected to be started";
}

TEST(TestEnv, set_local_env_id)
{
    TestModule::set_init_func(init_func, nullptr);
    TestModule::set_start_func(set_local_env_id_start_func, nullptr);

    P::Env::get()->run("dist/env" /* binary_path */, "tests/env_test.config");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
