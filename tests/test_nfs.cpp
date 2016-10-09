/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <stdio.h>
#include <gtest/gtest.h>
#include <thread>
#include "estore/estore.hpp"
#include "modules/i_module_agent.rpc.client.hpp"
#include "plasma/execution/env.hpp"
#include "test_module.hpp"
#include "globals.hpp"

static bool server_mode = false;

static const P::VMsg::ModuleAddress dest = {
    1,
    0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
    (uint8_t) ModuleId::I,  // module_id : 4
    0  // silo_id
};

static void start_func(void *ctx)
{
    IModuleAgentClient client;
    client.init();

    EXPECT_EQ(P::VMsg::VMsgRes::OK, client.activate_sync(dest));
}

TEST(TestNfs, test)
{
    // create the element store
    EStore::EStore estore;
    estore.init(0, ModuleId::I, FiberGroupId::I_CONTROL, nullptr);
    estore.create_estore();
    estore.destroy();

    global_debugging = true;

    TestModule::set_start_func(start_func, nullptr);

    P::Env *env = P::Env::get();
    std::thread env_thread(&P::Env::run, env, "" /* binary_path */, "tests/nfs_test.config");
    // wait for the env to start
    while (env->get_state() != P::EnvState::RUN) {
        usleep(100);
    }

    if (server_mode) {
        printf("NFS server is up, press any key to shutdown\n");
        getchar();
    } else {
        printf("running nfstest_posix\n");
        int ret = system("nfstest_posix --nfsversion=3 -s 127.0.0.1");
        ASSERT_EQ(ret, 0);
        printf("nfstest_posix done\n");
    }
    global_env_stop = true;
    env_thread.join();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    LOOP(argc, i) {
        if (strcmp(argv[i], "server") == 0) {
            server_mode = true;
        }
    }
    return RUN_ALL_TESTS();
}
