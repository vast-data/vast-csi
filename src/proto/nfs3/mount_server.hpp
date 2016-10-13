/* Copyright (C) Vast Data Ltd. */
/*!
 * \file mount_server.hpp
 * \brief The mount server, implements the mount protocol as defined in https://tools.ietf.org/html/rfc1813#page-106.
 */

#pragma once

#include "rpc.hpp"
#include "nfs_defs.hpp"
#include "rpcgen/mnt3.h"

namespace EStore {
class EStore;
}

namespace Nfs {

class MountServer : public RpcService {
public:
    void init(EStore::EStore *estore);
    void destroy();

    virtual void set_xdr_procs(RpcRequest *request) override;
    virtual void run_procedure(RpcRequest *request) override;

private:
    void null();
    void mnt(RpcRequest *request, dirpath *path, mountres3 *res);
    void dump(RpcRequest *request, mountlist *res);
    void umnt(RpcRequest *request, dirpath *path);
    void umntall(RpcRequest *request);
    void list_export(RpcRequest *request, exports *exports_list);

private:
    EStore::EStore *_estore;
};

}



