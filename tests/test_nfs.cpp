/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <stdio.h>
#include <gtest/gtest.h>
#include <thread>
#include "estore/estore.hpp"
#include "plasma/execution/env.hpp"
#include "globals.hpp"

static bool server_mode = false;

TEST(TestNfs, test)
{
    // create the element store
    EStore::EStore estore;
    estore.init();
    estore.create_estore();
    estore.destroy();

    debugging = true;
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
    env_stop = true;
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
