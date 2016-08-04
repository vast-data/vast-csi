/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <stdio.h>
#include <gtest/gtest.h>
#include <thread>
#include <rpc/clnt.h>
#include <proto/nfs3/rpcgen/nfs3.h>
#include "proto/nfs3/rpcgen/mnt3.h"
#include "proto/nfs3/rpcgen/nlm4.h"
#include "plasma/execution/env.hpp"
#include "globals.hpp"

static struct timeval TIMEOUT = { 2, 0 };

void test_nfs3_bad_version()
{
    CLIENT *nfs_clnt = clnt_create("127.0.0.1", NFS_PROGRAM, 1, "tcp");
    struct rpc_err error;
    ASSERT_NOT_NULL(nfs_clnt);

    int res = clnt_call(nfs_clnt, NFSPROC3_NULL,
                        (xdrproc_t) xdr_void, (caddr_t) nullptr,
                        (xdrproc_t) xdr_void, (caddr_t) nullptr,
                        TIMEOUT);

    ASSERT(res == RPC_PROGVERSMISMATCH)
    clnt_geterr(nfs_clnt, &error);
    ASSERT(error.ru.RE_vers.low == 3)
    ASSERT(error.ru.RE_vers.high == 3)

    clnt_destroy(nfs_clnt);
}

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
    for (int i = 0; i < 100; ++i) {
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

void test_nfs3_getattr()
{
    const char *dir_path = "/";
    mountres3 mnt_res3;
    GETATTR3args getattr_args3;
    GETATTR3res getattr_res3;
    AUTH *auth = authunix_create_default();
    CLIENT *mnt_clnt = clnt_create("127.0.0.1", MOUNT_PROGRAM, MOUNT_V3, "tcp");
    CLIENT *nfs_clnt = clnt_create("127.0.0.1", NFS_PROGRAM, NFS_V3, "tcp");
    ASSERT_NOT_NULL(mnt_clnt);
    ASSERT_NOT_NULL(nfs_clnt);

    memset(&mnt_res3, '\0', sizeof mnt_res3);
    memset(&getattr_res3, '\0', sizeof getattr_res3);
    mnt_clnt->cl_auth = auth;
    nfs_clnt->cl_auth = auth;

    if (clnt_call(mnt_clnt, MOUNTPROC3_MNT,
                 (xdrproc_t) xdr_dirpath, (caddr_t) &dir_path,
                 (xdrproc_t) xdr_mountres3, (caddr_t) &mnt_res3,
                 TIMEOUT) != RPC_SUCCESS) {
        printf("MNT call failed\n");
        abort();
    }

    if (mnt_res3.fhs_status != MNT3_OK) {
        printf("MNT failed\n");
        abort();
    }

    getattr_args3.object.data.data_len = mnt_res3.mountres3_u.mountinfo.fhandle.fhandle3_len;
    getattr_args3.object.data.data_val = mnt_res3.mountres3_u.mountinfo.fhandle.fhandle3_val;

    if (clnt_call(nfs_clnt, NFSPROC3_GETATTR,
                 (xdrproc_t) xdr_GETATTR3args, (caddr_t) &getattr_args3,
                 (xdrproc_t) xdr_GETATTR3res, (caddr_t) &getattr_res3,
                 TIMEOUT) != RPC_SUCCESS) {
        printf("GETATTR call failed\n");
        abort();
    }

    if (clnt_call(mnt_clnt, MOUNTPROC3_UMNT,
                 (xdrproc_t) xdr_dirpath, (caddr_t) &dir_path,
                 (xdrproc_t) xdr_void, (caddr_t) NULL,
                 TIMEOUT) != RPC_SUCCESS) {
        printf("UMNT call failed\n");
        abort();
    }

    ASSERT(getattr_res3.status == NFS3_OK)
    ASSERT(getattr_res3.GETATTR3res_u.resok.obj_attributes.type == NF3DIR)
    ASSERT(clnt_freeres(mnt_clnt, (xdrproc_t) xdr_mountres3, (caddr_t) &mnt_res3) == 1);
    ASSERT(clnt_freeres(mnt_clnt, (xdrproc_t) xdr_GETATTR3res, (caddr_t) &getattr_res3) == 1);
    clnt_destroy(mnt_clnt);
    clnt_destroy(nfs_clnt);
    auth_destroy(auth);
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
    ASSERT_NOT_NULL(udp_clnt);
    udp_clnt->cl_auth = auth;

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


    for (int i = 0; i < 100; ++i) {
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
    P::Env *env = P::Env::get();
    std::thread env_thread(&P::Env::run, env, "tests/nfs_test.config");
    // wait for the env to start
    while (env->get_state() != P::EnvState::RUN) {
        usleep(100);
    }
    test_mount();
    test_nfs();
    test_nfs3_getattr();
    test_nfs3_bad_version();

    env_stop = true;
    env_thread.join();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
