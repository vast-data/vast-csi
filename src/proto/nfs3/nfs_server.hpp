#/* Copyright (C) Vast Data Ltd. */
/*!
 * \file nfs_server.hpp
 * \brief The nfs server, implements the nfs protocol as defined in https://tools.ietf.org/html/rfc1813.
 */

#pragma once

#include <sys/stat.h>
#include "estore/estore.hpp"
#include "rpc.hpp"

namespace Nfs {

struct ReaddirState {
    NfsServer *srv;
    uint64_t mem_left;
    uint64_t dir_mem_left;
    void *next_entry;
    entry3 *rd_entry;
    entryplus3 *rdp_entry;
    bool last_retval;
};

// used for permission checks, corresponds to unix mode bits
static const uint32_t READ_MODE = 04;
static const uint32_t WRITE_MODE = 02;
static const uint32_t EXEC_MODE = 01;

class NfsServer : public RpcService {
public:
    void init(NfsConfig *nfs_conf, EStore::EStore *estore);
    void destroy();

    virtual void set_xdr_procs(RpcRequest *request) override;
    virtual void run_procedure(RpcRequest *request) override;

    bool readdir_plus_cb(EStore::ReaddirEntry *entry, void *ctx);

private:
    // nfs procedures
    void get_attr(RpcRequest *request, GETATTR3args *args, GETATTR3res *res);
    void set_attr(RpcRequest *request, SETATTR3args *args, SETATTR3res *res);
    void lookup(RpcRequest *request, LOOKUP3args *args, LOOKUP3res *res);
    void access(RpcRequest *request, ACCESS3args *args, ACCESS3res *res);
    void readlink(RpcRequest *request, READLINK3args *args, READLINK3res *res);
    void read(RpcRequest *request, READ3args *args, BufferedREAD3res *res);
    void write(RpcRequest *request, BufferedWRITE3args *args, WRITE3res *res);
    void create(RpcRequest *request, CREATE3args *args, CREATE3res *res);
    void mkdir(RpcRequest *request, MKDIR3args *args, MKDIR3res *res);
    void symlink(RpcRequest *request, SYMLINK3args *args, SYMLINK3res *res);
    void mknod(RpcRequest *request, MKNOD3args *args, MKNOD3res *res);
    void remove(RpcRequest *request, REMOVE3args *args, REMOVE3res *res);
    void rmdir(RpcRequest *request, RMDIR3args *args, RMDIR3res *res);
    void rename(RpcRequest *request, RENAME3args *args, RENAME3res *res);
    void link(RpcRequest *request, LINK3args *args, LINK3res *res);
    void readdir(RpcRequest *request, READDIR3args *args, READDIR3res *res);
    void readdir_plus(RpcRequest *request, READDIRPLUS3args *args, READDIRPLUS3res *res);
    void fsstat(RpcRequest *request, FSSTAT3args *args, FSSTAT3res *res);
    void fsinfo(RpcRequest *request, FSINFO3args *args, FSINFO3res *res);
    void pathconf(RpcRequest *request, PATHCONF3args *args, PATHCONF3res *res);
    void commit(RpcRequest *request, COMMIT3args *args, COMMIT3res *res);

    // helper methods
    void unlink(RpcRequest *request, diropargs3 *args, nfsstat3 *status, wcc_data *resok, wcc_data *resfail);
    EStore::EStoreRes add_dot_files(EStore::EHandle handle, uint64_t offset,
                                    ReaddirState *rd_state, EStore::ReaddirCallback cb);
    void sys_attr_to_nfs_attr(EStore::SystemAttr *attr, fattr3 *nfs_attr);
    EStore::EStoreRes fill_post_op_attr(nfs_fh3 *fh3, post_op_attr *po_attr);
    EStore::EStoreRes get_attr_from_fh3(nfs_fh3 *fh3, fattr3 *attr);
    nfsstat3 eres_to_nfs_status(EStore::EStoreRes res);
    void nfs_sattr_to_settable_attr(sattr3 *nfs_sattr, EStore::SettableAttr *sattr);
    void fill_create_resok(CREATE3resok *resok, EStore::EHandle ehandle, EStore::SystemAttr eattr,
                           EStore::SystemAttr pre_pattr, EStore::SystemAttr post_pattr);
    void sys_attr_to_wcc_attr(EStore::SystemAttr *attr, wcc_attr *wcc_attr);
    void fill_wcc_data(wcc_data *wcc_data, EStore::SystemAttr *pre_attr, EStore::SystemAttr *post_attr);
    void nfs_access_to_mode(bool is_dir, uint32 *access, uint32_t *mode);
    void mode_to_nfs_access(uint32_t mode, uint32_t *access);
    void set_owner_from_auth(EStore::SettableAttr *sattr, RpcRequest *request);

private:
    const char *SYMLINK_XATTR = "nfs3_symlink";

    EStore::EStore *_estore;
    NfsConfig _nfs_conf;
};

}
