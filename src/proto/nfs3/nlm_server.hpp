/* Copyright (C) Vast Data Ltd. */
/*!
 * \file nlm_server.hpp
 * \brief The nlm server
 */

#pragma once

#include "rpc.hpp"
#include "nfs_defs.hpp"
#include "rpcgen/nlm4.h"

namespace EStore {
class EStore;
}

namespace Nfs {

class NlmServer : public RpcService {
public:
    void init(EStore::EStore *estore);
    void destroy();

    virtual void set_xdr_procs(RpcRequest *request) override;
    virtual void run_procedure(RpcRequest *request) override;

private:
    void null();
    void test(RpcRequest *request, nlm4_testargs *arg, nlm4_testres *res);
    void lock(RpcRequest *request, nlm4_lockargs *arg, nlm4_res *res);
    void cancel(RpcRequest *request, nlm4_cancargs *arg, nlm4_res *res);
    void unlock(RpcRequest *request, nlm4_unlockargs *arg, nlm4_res *res);

private:
    EStore::EStore *_estore;
};

}



