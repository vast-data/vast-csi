/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>

#include "globals.hpp"
#include "modules/p_module_agent.rpc.client.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/utils/assert.hpp"
#include "test_module.hpp"

using namespace P::VMsg;

static void init_func(P::Silo *silo, void *ctx)
{
    // Nothing to do for now. Use if/when relevant.
}

static P::EnvStartResultCode send_env_start(VMsg *vmsg, P::GUID env_guid, const char *config)
{
    P::PModuleAgentClient client;
    client.init(vmsg);
    ModuleGUID dest = {
            0,  // env_id
            0,  // reserved : 4;
            // only the first 4 bits are in use for module ids
            (uint8_t) ModuleId::P,  // module_id : 4
            0  // silo_id
    };

    P::EnvStartParams::RootBuilder *env_start_params = client.alloc_env_start();
    env_start_params->set_env_guid(env_guid);
    strcpy(env_start_params->get_config(), config);
    P::EnvStartResult::RootReader *env_start_reply;
    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);
    EXPECT_EQ(VMsgRes::OK, client.env_start_sync(dest, env_start_params, &env_start_reply));
    P::EnvStartResultCode res = env_start_reply->get_code();
    client.free_env_start(env_start_reply);
    return res;
}

static P::EnvStopResultCode send_env_stop(VMsg *vmsg, P::GUID env_guid)
{
    P::PModuleAgentClient client;
    client.init(vmsg);
    ModuleGUID dest = {
            0,  // env_id
            0,  // reserved : 4;
            // only the first 4 bits are in use for module ids
            (uint8_t) ModuleId::P,  // module_id : 4
            0  // silo_id
    };

    P::EnvStopParams::RootBuilder *env_stop_params = client.alloc_env_stop();
    env_stop_params->set_env_guid(env_guid);
    P::EnvStopResult::RootReader *env_stop_reply;
    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);
    EXPECT_EQ(VMsgRes::OK, client.env_stop_sync(dest, env_stop_params, &env_stop_reply));
    P::EnvStopResultCode res = env_stop_reply->get_code();
    client.free_env_stop(env_stop_reply);
    return res;
}

static void env_start_stop_start_func(void *ctx)
{
    env_stop = false;

    if (P::Silo::get()->get_id() > 0) {
        return;
    }

    VMsg *vmsg = P::Env::get()->get_vmsg();
    vmsg->add_module_pair(ModuleId::TEST, ModuleId::P, TransportType::RDMA);
    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);  // TODO(ido): Asaf - why sleep? why define the other direction? and review all sleeps..
    vmsg->add_module_pair(ModuleId::P, ModuleId::TEST, TransportType::RDMA);

    P::GUID env_guid;
    env_guid.init();

    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(vmsg, env_guid));
    // TODO(ido): check..

    EXPECT_EQ(P::EnvStartResultCode::SUCCESS, send_env_start(vmsg, env_guid, "blah"));
    // TODO(ido): check..

    EXPECT_EQ(P::EnvStopResultCode::SUCCESS, send_env_stop(vmsg, env_guid));
    EXPECT_EQ(P::EnvStopResultCode::GUID_NOT_FOUND, send_env_stop(vmsg, env_guid));
    // TODO(ido): check..

    // TODO(ido): remove all printf's..

    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);

    env_stop = true;
}

// TODO(ido): testing set_local_env_id is problematic, because of its effect on vmsg. So 1) this should probably be the last test; 2) better remove it and test it as part of an integration test, when it's really needed (for other envs).
static void set_local_env_id_start_func(void *ctx)
{
    env_stop = false;

    if (P::Silo::get()->get_id() > 0) {
        return;
    }

    VMsg *vmsg = P::Env::get()->get_vmsg();
    vmsg->add_module_pair(ModuleId::TEST, ModuleId::P, TransportType::RDMA);
    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);
    vmsg->add_module_pair(ModuleId::P, ModuleId::TEST, TransportType::RDMA);

    P::GUID env_guid;
    env_guid.init();

    P::PModuleAgentClient client;
    client.init(vmsg);
    ModuleGUID dest = {
            0,  // env_id
            0,  // reserved : 4;
            // only the first 4 bits are in use for module ids
            (uint8_t) ModuleId::P,  // module_id : 4
            0  // silo_id
    };

    P::SetLocalEnvIdParams::RootBuilder *set_local_env_id_params = client.alloc_set_local_env_id();
    set_local_env_id_params->set_env_id(123);
    P::VProto::Empty::RootReader *set_local_env_id_reply;
    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);
    EXPECT_EQ(0, vmsg->get_local_env_id());
    EXPECT_EQ(VMsgRes::OK, client.set_local_env_id_sync(dest, set_local_env_id_params, &set_local_env_id_reply));
    client.free_set_local_env_id(set_local_env_id_reply);
    EXPECT_EQ(123, vmsg->get_local_env_id());

    P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);

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
