#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>
#include "plasma/utils/units.hpp"
#include "plasma/utils/io.hpp"
#include "rpcgen/rpc_defs.h"
#include "rpcgen/nfs3.h"
#include "rpcgen/mnt3.h"
#include "rpcgen/nlm4.h"

namespace Nfs {

enum ProtocolType {
    NFS3,
    MOUNT3,
    NLM4,

    COUNT
};
static const uint16_t PROTOCOL_COUNT = ProtocolType::COUNT;

struct NfsConfig {
    bool enabled;
    uint32_t port[PROTOCOL_COUNT];
    uint32_t max_read_size;
    uint32_t max_write_size;
    uint32_t connections_per_silo;
    uint32_t requests_per_silo;
};

// how many times to retry a resource allocation before failing an operation
static const uint32_t ALLOCATION_RETRY = 4096;
// how many times to retry send / recv before failing an operation
static const uint32_t SEND_RETRY = 4096;
static const uint32_t RECV_RETRY = 4096;

struct BufferedWRITE3args {
    nfs_fh3 file;
    offset3 offset;
    count3 count;
    stable_how stable;
    u_int data_len;
    P::IOVecs io_vecs;
};

struct BufferedREAD3resok {
    post_op_attr file_attributes;
    count3 count;
    bool_t eof;
    u_int data_len;
    P::IOVecs io_vecs;
};

struct BufferedREAD3res {
    nfsstat3 status;
    union {
        BufferedREAD3resok resok;
        READ3resfail resfail;
    } READ3res_u;
};

union NfsArgs {
    // nfs3
    GETATTR3args getattr;
    SETATTR3args setattr;
    LOOKUP3args lookup;
    ACCESS3args access;
    READLINK3args readlink;
    READ3args read;
    BufferedWRITE3args write;
    CREATE3args create;
    MKDIR3args mkdir;
    SYMLINK3args symlink;
    MKNOD3args mknod;
    REMOVE3args remove;
    RMDIR3args rmdir;
    RENAME3args rename;
    LINK3args link;
    READDIR3args readdir;
    READDIRPLUS3args readdirplus;
    FSSTAT3args fsstat;
    FSINFO3args fsinfo;
    PATHCONF3args pathconf;
    COMMIT3args commit;

    // mnt3
    dirpath mnt_dirpath;

    // nlm
    nlm4_testargs test_args;
    nlm4_lockargs lock_args;
    nlm4_cancargs cancel_args;
    nlm4_unlockargs unlock_args;
};

union NfsRes {
    //nfs3
    GETATTR3res getattr;
    SETATTR3res setattr;
    LOOKUP3res lookup;
    ACCESS3res access;
    READLINK3res readlink;
    BufferedREAD3res read;
    WRITE3res write;
    CREATE3res create;
    MKDIR3res mkdir;
    SYMLINK3res symlink;
    MKNOD3res mknod;
    REMOVE3res remove;
    RMDIR3res rmdir;
    RENAME3res rename;
    LINK3res link;
    READDIR3res readdir;
    READDIRPLUS3res readdirplus;
    FSSTAT3res fsstat;
    FSINFO3res fsinfo;
    PATHCONF3res pathconf;
    COMMIT3res commit;

    // mnt3
    exports mntexport;
    mountres3 mnt_res;
    mountlist dump_res;

    // nlm4
    nlm4_testres nlm4_test_res;
    nlm4_res nlm4_res;
};

enum class RpcStatus {
    OK,
    AUTH_FAILURE,       // authorization error
    DECODE_ERROR,       // decode failed
    PROG_NOT_FOUND,     // program not found
    VER_NOT_SUPPORTED,  // unsupported version
    PROC_NOT_FOUND,     // unsupported procedure
};

struct NfsArgsBuffer {
    char fh0[FHSIZE3];
    char fh1[FHSIZE3];
    char name0[NAME_MAX+1];
    char name1[NAME_MAX+1];
};

struct NfsArgsBufferWith4K {
    char fh[FHSIZE3];
    char name[NAME_MAX+1];
    char _4k[PATH_MAX+1];
};

struct NlmArgsBuffer {
    char netobj0[MAXNETOBJ_SZ];
    char netobj1[MAXNETOBJ_SZ];
    char netobj2[MAXNETOBJ_SZ];
    char caller_name[LM_MAXSTRLEN];
};

// biggest reply is readlink
static const uint32_t RES_BUFFER_SIZE = PATH_MAX + 1;

struct RpcRequest {
    // request status
    RpcStatus status;
    // rpc message structure
    vrpc_msg msg;
    // buffers for storing auth data
    char auth_cred_buffer[AUTH_SIZE];
    char auth_verf_buffer[AUTH_SIZE];
    char machine_name[MACHINE_NAME_LEN];
    u_int gids[MAX_GIDS];
    // auth unix data
    bool unix_auth_set;
    vauthsys_parms auth_params;
    // sender address (used for udp)
    struct sockaddr_in addr;
    socklen_t addr_len;
    // buffers for storing dynamic arguments (e.g. names and paths)
    union {
        char args_buffer[0];
        NfsArgsBuffer args_buffer_nfs;
        NfsArgsBufferWith4K args_buffer_nfs_with_4k;
        NlmArgsBuffer args_buffer_nlm;
    };
    union {
        char res_buffer[RES_BUFFER_SIZE];
        NlmArgsBuffer res_buffer_nlm;
    };
    // nfs args / result unions
    NfsArgs args;
    NfsRes res;
    // xdr translation functions
    xdrproc_t args_proc;
    xdrproc_t res_proc;
    xdrproc_t free_proc;
    // request context
    void *conn;
    void *rpc;
};

}
