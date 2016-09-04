#include <proto/nfs3/rpcgen/nlm4.h>
#include <limits>
#include <rpc/xdr.h>
#include "nfs_defs.hpp"
#include "nfs_utils.hpp"
#include "nlm_server.hpp"

using EStore::EStoreRes;
using EStore::EHandle;

#define CURRENT_COMPONENT ComponentId::NFS

namespace Nfs {

void NlmServer::init(EStore::EStore *estore)
{
    _estore = estore;
}

void NlmServer::destroy()
{

}

void NlmServer::set_xdr_procs(RpcRequest *request)
{
    request->free_proc = nullptr;
    request->args_proc = nullptr;
    request->res_proc = nullptr;
    switch (request->msg.body.vrpc_msg_body_u.cbody.proc) {
        case NLMPROC4_NULL:
            request->args_proc = (xdrproc_t)xdr_void;
            request->res_proc = (xdrproc_t)xdr_void;
            break;
        
        case NLMPROC4_TEST:
            request->args.test_args.cookie.n_bytes = request->args_buffer_nlm.netobj0;
            request->args.test_args.alock.caller_name = request->args_buffer_nlm.caller_name;
            request->args.test_args.alock.fh.n_bytes = request->args_buffer_nlm.netobj1;
            request->args.test_args.alock.oh.n_bytes = request->args_buffer_nlm.netobj2;
            request->res.nlm4_test_res.cookie.n_bytes = request->res_buffer_nlm.netobj0;
            request->res.nlm4_test_res.test_stat.nlm4_testrply_u.holder.oh.n_bytes = request->res_buffer_nlm.netobj1;
            request->args_proc = (xdrproc_t)xdr_nlm4_testargs;
            request->res_proc = (xdrproc_t)xdr_nlm4_testres;
            break;

        case NLMPROC4_LOCK:
            request->args.lock_args.cookie.n_bytes = request->args_buffer_nlm.netobj0;
            request->args.lock_args.alock.caller_name = request->args_buffer_nlm.caller_name;
            request->args.lock_args.alock.fh.n_bytes = request->args_buffer_nlm.netobj1;
            request->args.lock_args.alock.oh.n_bytes = request->args_buffer_nlm.netobj2;
            request->res.nlm4_res.cookie.n_bytes = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_nlm4_lockargs;
            request->res_proc = (xdrproc_t)xdr_nlm4_res;
            break;

        case NLMPROC4_CANCEL:
            request->args.cancel_args.cookie.n_bytes = request->args_buffer_nlm.netobj0;
            request->args.cancel_args.alock.caller_name = request->args_buffer_nlm.caller_name;
            request->args.cancel_args.alock.fh.n_bytes = request->args_buffer_nlm.netobj1;
            request->args.cancel_args.alock.oh.n_bytes = request->args_buffer_nlm.netobj2;
            request->res.nlm4_res.cookie.n_bytes = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_nlm4_cancargs;
            request->res_proc = (xdrproc_t)xdr_nlm4_res;
            break;

        case NLMPROC4_UNLOCK:
            request->args.unlock_args.cookie.n_bytes = request->args_buffer_nlm.netobj0;
            request->args.unlock_args.alock.caller_name = request->args_buffer_nlm.caller_name;
            request->args.unlock_args.alock.fh.n_bytes = request->args_buffer_nlm.netobj1;
            request->args.unlock_args.alock.oh.n_bytes = request->args_buffer_nlm.netobj2;
            request->res.nlm4_res.cookie.n_bytes = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_nlm4_unlockargs;
            request->res_proc = (xdrproc_t)xdr_nlm4_res;
            break;

        default:
            PT_ERROR(DATA, "proc not found");
            request->status = RpcStatus::PROC_NOT_FOUND;
            return;
    }

}

void NlmServer::run_procedure(RpcRequest *request)
{
    switch (request->msg.body.vrpc_msg_body_u.cbody.proc) {
        case NLMPROC4_NULL:
            break;

        case NLMPROC4_TEST:
            test(request, &request->args.test_args, &request->res.nlm4_test_res);
            break;

        case NLMPROC4_LOCK:
            lock(request, &request->args.lock_args, &request->res.nlm4_res);
            break;

        case NLMPROC4_CANCEL:
            cancel(request, &request->args.cancel_args, &request->res.nlm4_res);
            break;

        case NLMPROC4_UNLOCK:
            unlock(request, &request->args.unlock_args, &request->res.nlm4_res);
            break;

        default:
            PT_ERROR(DATA, "proc not found");
            request->status = RpcStatus::PROC_NOT_FOUND;
            return;
    }
    return;
}

void NlmServer::test(RpcRequest *request, nlm4_testargs *arg, nlm4_testres *res)
{
    EStore::LockInfo lock;
    EStore::LockInfo existing_lock;
    EStore::EHandle handle;
    
    nlm4_lock_to_handle(&arg->alock, &handle);
    nlm4_lock_to_lock_info(arg->exclusive, &arg->alock, &lock);
    EStoreRes eres = _estore->test_lock(nullptr, nullptr, handle, &lock, &existing_lock);
    
    request->res.nlm4_test_res.cookie.n_bytes = request->args.test_args.cookie.n_bytes;
    request->res.nlm4_test_res.cookie.n_len = request->args.test_args.cookie.n_len;

    switch (eres) {
        case EStoreRes::OK:
            res->test_stat.stat = NLM4_GRANTED;
            break;
        case EStoreRes::LOCKED:
        {
            nlm4_holder *holder = &res->test_stat.nlm4_testrply_u.holder;
            netobj *lock_oh = &holder->oh;
            res->test_stat.stat = NLM4_DENIED;
            holder->exclusive = existing_lock.exclusive;
            holder->svid = existing_lock.svid;
            holder->l_offset = existing_lock.start;
            holder->l_len = existing_lock.end == UINT64_MAX ? 0 : existing_lock.end - existing_lock.start;
            lock_oh->n_len = existing_lock.owner_len;
            memcpy(lock_oh->n_bytes, existing_lock.owner, existing_lock.owner_len);
            break;
        }
        default:
            PT_ERROR(DATA, "nlm4_test on handle=%lx failed res=%d", handle, eres);
            res->test_stat.stat = NLM4_FAILED;
    }
}

void NlmServer::lock(RpcRequest *request, nlm4_lockargs *arg, nlm4_res *res)
{
    EStore::LockInfo lock;
    EStore::EHandle handle;
    
    nlm4_lock_to_handle(&arg->alock, &handle);
    nlm4_lock_to_lock_info(arg->exclusive, &arg->alock, &lock);
    EStoreRes eres = _estore->lock(nullptr, nullptr, handle, arg->block, &lock);
    
    request->res.nlm4_res.cookie.n_bytes = request->args.lock_args.cookie.n_bytes;
    request->res.nlm4_res.cookie.n_len = request->args.lock_args.cookie.n_len;

    switch (eres) {
        case EStoreRes::OK:
            res->stat.stat = NLM4_GRANTED;
            break;
        case EStoreRes::LOCKED:
            res->stat.stat = NLM4_DENIED;
            break;
        default:
            PT_ERROR(DATA, "nlm4_lock on handle=%lx failed res=%d", handle, eres);
            res->stat.stat = NLM4_FAILED;
    }
}

void NlmServer::cancel(RpcRequest *request, nlm4_cancargs *arg, nlm4_res *res)
{
    request->res.nlm4_res.cookie.n_bytes = request->args.cancel_args.cookie.n_bytes;
    request->res.nlm4_res.cookie.n_len = request->args.cancel_args.cookie.n_len;

    res->stat.stat = NLM4_GRANTED;
}

void NlmServer::unlock(RpcRequest *request, nlm4_unlockargs *arg, nlm4_res *res)
{
    EStore::LockInfo lock;
    EStore::EHandle handle;
    
    nlm4_lock_to_handle(&arg->alock, &handle);
    nlm4_lock_to_lock_info(true, &arg->alock, &lock);
    EStoreRes eres = _estore->unlock(nullptr, nullptr, handle, &lock);
    
    request->res.nlm4_res.cookie.n_bytes = request->args.unlock_args.cookie.n_bytes;
    request->res.nlm4_res.cookie.n_len = request->args.unlock_args.cookie.n_len;

    switch (eres) {
        case EStoreRes::OK:
            res->stat.stat = NLM4_GRANTED;
            break;
        case EStoreRes::LOCKED:
            res->stat.stat = NLM4_DENIED;
            break;
        default:
            PT_ERROR(DATA, "nlm4_unlock on handle=%lx failed res=%d", handle, eres);
            res->stat.stat = NLM4_FAILED;
    }
}

}


