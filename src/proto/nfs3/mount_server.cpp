#include <proto/nfs3/rpcgen/mnt3.h>
#include "mount_server.hpp"

using EStore::EStoreRes;
using EStore::EHandle;

#define CURRENT_COMPONENT ComponentId::NFS

namespace Nfs {

void MountServer::init(EStore::EStore *estore)
{
    _estore = estore;
    EStore::EHandle handle;
    _estore->get_root_handle(&handle);
}

void MountServer::destroy()
{

}

void MountServer::set_xdr_procs(RpcRequest *request)
{
    request->free_proc = nullptr;
    request->args_proc = nullptr;
    request->res_proc = nullptr;
    switch (request->msg.body.vrpc_msg_body_u.cbody.proc) {
        case MOUNTPROC3_NULL:
            request->args_proc = (xdrproc_t)xdr_void;
            request->res_proc = (xdrproc_t)xdr_void;
            break;

        case MOUNTPROC3_MNT:
            request->args.mnt_dirpath = request->args_buffer;
            request->res.mnt_res.mountres3_u.mountinfo.fhandle.fhandle3_val = request->res_buffer;
            request->res.mnt_res.mountres3_u.mountinfo.auth_flavors.auth_flavors_val =
                (int *)(request->res_buffer + FHSIZE3);
            request->args_proc = (xdrproc_t)xdr_dirpath;
            request->res_proc = (xdrproc_t)xdr_mountres3;
            break;

        case MOUNTPROC3_DUMP:
            request->args_proc = (xdrproc_t)xdr_void;
            request->res_proc = (xdrproc_t)xdr_mountlist;
            break;

        case MOUNTPROC3_UMNT:
            request->args.mnt_dirpath = request->args_buffer;
            request->args_proc = (xdrproc_t)xdr_dirpath;
            request->res_proc = (xdrproc_t)xdr_void;
            break;

        case MOUNTPROC3_UMNTALL:
            request->args_proc = (xdrproc_t)xdr_void;
            request->res_proc = (xdrproc_t)xdr_void;
            break;

        case MOUNTPROC3_EXPORT:
            request->args_proc = (xdrproc_t)xdr_void;
            request->res_proc = (xdrproc_t)xdr_exports;
            break;

        default:
            PT_ERROR("proc not found");
            request->status = RpcStatus::PROC_NOT_FOUND;
            return;
    }
}

void MountServer::run_procedure(RpcRequest *request)
{
    switch (request->msg.body.vrpc_msg_body_u.cbody.proc) {
        case MOUNTPROC3_NULL:
            break;

        case MOUNTPROC3_MNT:
            mnt(request, &request->args.mnt_dirpath, &request->res.mnt_res);
            break;

        case MOUNTPROC3_DUMP:
            dump(request, &request->res.dump_res);
            break;

        case MOUNTPROC3_UMNT:
            umnt(request, &request->args.mnt_dirpath);
            break;

        case MOUNTPROC3_UMNTALL:
            umntall(request);
            break;

        case MOUNTPROC3_EXPORT:
            list_export(request, &request->res.mntexport);
            break;

        default:
            PT_ERROR("proc not found");
            request->status = RpcStatus::PROC_NOT_FOUND;
            return;
    }
    return;
}

void MountServer::mnt(RpcRequest *request, dirpath *path, mountres3 *res)
{
    static int auth_unix_val = AUTH_UNIX;

    // until there is a cluster wide configuration available we only support mounting the root
    // TODO verify client host is allowed to access the export
    if (strncmp(*path, "/", MNTPATHLEN) != 0) {
        res->fhs_status = MNT3ERR_NOENT;
        return;
    }
    // TODO add to active mount list (global to Env / Cluster)?
    EHandle root_handle;
    _estore->get_root_handle(&root_handle);

    PT_INFO("mnt request path=%s", *path);
    res->fhs_status = MNT3_OK;
    res->mountres3_u.mountinfo.fhandle.fhandle3_len = sizeof(EHandle);
    *(EHandle*)res->mountres3_u.mountinfo.fhandle.fhandle3_val = root_handle;
    res->mountres3_u.mountinfo.auth_flavors.auth_flavors_len = 1;
    res->mountres3_u.mountinfo.auth_flavors.auth_flavors_val = &auth_unix_val;
}

void MountServer::dump(RpcRequest *request, mountlist *res)
{
    // need to understand if someone is actually using this API
    PANIC("not implemented");
}

void MountServer::umnt(RpcRequest *request, dirpath *path)
{
    // TODO remove from active mount list
    PT_INFO("umnt request path=%s", *path);
}

void MountServer::umntall(RpcRequest *request)
{
    // need to understand if someone is actually using this API
    PANIC("not implemented");
}

void MountServer::list_export(RpcRequest *request, exports *exports_list)
{
    // need to understand if someone is actually using this API
    PANIC("not implemented");
}

}


