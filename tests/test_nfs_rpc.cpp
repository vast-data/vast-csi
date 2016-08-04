/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <stdio.h>
#include <gtest/gtest.h>
#include <thread>
#include <rpc/clnt.h>
#include <proto/nfs3/rpcgen/nfs3.h>
#include "proto/nfs3/rpcgen/mnt3.h"
#include "plasma/execution/env.hpp"
#include "globals.hpp"

static struct timeval TIMEOUT = { 2, 0 };

void send_mount_msgs(CLIENT *clnt)
{
    void  *clnt_res;
    char *mountproc3_null_3_arg;

    if (clnt_call(clnt, MOUNTPROC3_NULL,
                  (xdrproc_t) xdr_void, (caddr_t) mountproc3_null_3_arg,
                  (xdrproc_t) xdr_void, (caddr_t) &clnt_res,
                  TIMEOUT) != RPC_SUCCESS) {
        printf("call failed\n");
        abort();
    }

    mountres3 mnt_res;
    char bla[8];
    sprintf(bla, "/");
    dirpath dirp = bla;
    for (int i = 0; i < 1000; ++i) {
        memset((char *)&mnt_res, 0, sizeof(mnt_res));
        if (clnt_call(clnt, MOUNTPROC3_MNT,
                      (xdrproc_t) xdr_dirpath, (caddr_t) &dirp,
                      (xdrproc_t) xdr_mountres3, (caddr_t) &mnt_res,
                      TIMEOUT) != RPC_SUCCESS) {
            printf("call failed\n");
            abort();
        }
        if (clnt_call(clnt, MOUNTPROC3_UMNT,
                      (xdrproc_t) xdr_dirpath, (caddr_t) &dirp,
                      (xdrproc_t) xdr_void, (caddr_t) NULL,
                      TIMEOUT) != RPC_SUCCESS) {
            printf("call failed\n");
            abort();
        }
    }
}

void test_mount()
{
    AUTH *auth = authunix_create_default();
    CLIENT *tcp_clnt;
    CLIENT *udp_clnt;
    tcp_clnt = clnt_create("127.0.0.1", MOUNT_PROGRAM, MOUNT_V3, "tcp");
    ASSERT_NOT_NULL(tcp_clnt);
    tcp_clnt->cl_auth = auth;

    udp_clnt = clnt_create("127.0.0.1", MOUNT_PROGRAM, MOUNT_V3, "udp");
    udp_clnt->cl_auth = auth;
    ASSERT_NOT_NULL(udp_clnt);

    send_mount_msgs(tcp_clnt);
    clnt_destroy(tcp_clnt);
    tcp_clnt = clnt_create("127.0.0.1", MOUNT_PROGRAM, MOUNT_V3, "tcp");
    ASSERT_NOT_NULL(tcp_clnt);
    tcp_clnt->cl_auth = auth;
    send_mount_msgs(tcp_clnt);
    clnt_destroy(tcp_clnt);

    send_mount_msgs(udp_clnt);
    clnt_destroy(udp_clnt);
    auth_destroy(auth);
}

void test_nfs()
{
    // note: this isn't really testing much, need to decide if its worth the investment vs just using existing tools
    AUTH *auth = authunix_create_default();
    CLIENT *clnt = clnt_create("127.0.0.1", NFS_PROGRAM, NFS_V3, "tcp");
    ASSERT_NOT_NULL(clnt);
    clnt->cl_auth = auth;


    for (int i = 0; i < 1000; ++i) {
        if (clnt_call(clnt, NFSPROC3_NULL,
                      (xdrproc_t) xdr_void, (caddr_t) NULL,
                      (xdrproc_t) xdr_void, (caddr_t) NULL,
                      TIMEOUT) != RPC_SUCCESS) {
            printf("call failed\n");
            abort();
        }
    }

    clnt_destroy(clnt);
    auth_destroy(auth);
}

TEST(TestNfsRpc, test)
{
    debugging = true;
    std::thread env_thread(&P::Env::run, P::Env::get(), "tests/nfs_test.config");
    // wait for the env to start
    usleep(10000);
    test_mount();
    test_nfs();

    env_stop = true;
    env_thread.join();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
