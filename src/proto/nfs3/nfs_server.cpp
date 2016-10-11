#include <sys/stat.h>
#include <limits>
#include <proto/nfs3/rpcgen/nfs3.h>
#include <plasma/utils/units.hpp>
#include "nfs_server.hpp"
#include "nfs_utils.hpp"
#include "estore/estore.hpp"
#include "nfs_defs.hpp"
#include <cmath>
#include <string.h>
#include <proto/nfs3/rpcgen/rpc_defs.h>
#include <unistd.h>

#define CURRENT_COMPONENT ComponentId::NFS

using EStore::EHandle;
using EStore::EStoreRes;
using EStore::ExtendedAttr;
using EStore::ExtendedAttrs;
using EStore::SettableAttr;
using EStore::SystemAttr;
using EStore::AttrFlag;
using EStore::ElementFlags;
using EStore::CreateFlags;
using EStore::OpCallback;
using EStore::ListCallback;
using P::IO::IOVec;
using P::IO::IOVecs;

namespace Nfs {

void NfsServer::init(NfsConfig *nfs_conf, EStore::EStore *estore)
{
    _estore = estore;
    _nfs_conf = *nfs_conf;
}

void NfsServer::destroy()
{
}

static void free_iovec(P::IO::IOVecs *iovecs, Rpc *rpc)
{
    rpc->free_data_buffers(iovecs);
}

// This is an optimized version of the auto generated xdr_WRITE3args function.
// It uses element store data buffers instead of causing XDR to allocate memory and it uses xdrdrec_direct_read
// in order to avoid mem copy for the write data.
bool_t
xdr_buffered_WRITE3args(XDR *xdrs, BufferedWRITE3args *objp)
{
    DEBUG_ASSERT(xdrs->x_op == XDR_DECODE);
    if (!xdr_nfs_fh3 (xdrs, &objp->file))
        return FALSE;
    if (!xdr_offset3 (xdrs, &objp->offset))
        return FALSE;
    if (!xdr_count3 (xdrs, &objp->count))
        return FALSE;
    if (!xdr_stable_how (xdrs, &objp->stable))
        return FALSE;
    if (!xdr_u_int(xdrs, &objp->data_len))
        return FALSE;

    Rpc *rpc = (Rpc *)xdrs->x_public;
    u_int len = objp->data_len;
    uint32_t n_buffers = (len / EStore::DATA_BUFFER_SIZE) + (len % EStore::DATA_BUFFER_SIZE ? 1 : 0);
    objp->io_vecs.count = 0;
    for (int i = 0; i < ALLOCATION_RETRY && objp->io_vecs.count == 0; ++i) {
        objp->io_vecs.count = n_buffers;
        rpc->alloc_data_buffers(&objp->io_vecs);
        if (objp->io_vecs.count == 0) {
            P::Fiber::yield();
        }
    }

    for (int i = 0; i < n_buffers && len > 0; ++i) {
        IOVec *vec = &objp->io_vecs.iovecs[i];
        vec->iov_len = P_MIN(len, EStore::DATA_BUFFER_SIZE);
        if (!xdrdrec_direct_read(xdrs, (caddr_t)vec->iov_base, vec->iov_len)) {
            PT_ERROR(DATA, "xdrdrec_direct_read failed");
            break;
        }
        len -= vec->iov_len;
    }
    if (len > 0) {
        PT_ERROR(DATA, "reading data failed");
        free_iovec(&objp->io_vecs, rpc);
        return FALSE;
    }
    return TRUE;
}

// This is an optimized version of the auto generated xdr_READ3args function.
// It uses element store data buffers instead of causing XDR to allocate memory and it uses xdrdrec_direct_write
// in order to avoid mem copy for the write data.
bool_t
xdr_buffered_READ3resok(XDR *xdrs, BufferedREAD3resok *objp)
{
    DEBUG_ASSERT(xdrs->x_op == XDR_ENCODE);
    if (!xdr_post_op_attr (xdrs, &objp->file_attributes))
        return FALSE;
    if (!xdr_count3 (xdrs, &objp->count))
        return FALSE;
    if (!xdr_bool (xdrs, &objp->eof))
        return FALSE;
    if (!xdr_u_int(xdrs, &objp->data_len))
        return FALSE;
    u_int len = objp->data_len;
    for (int i = 0; len > 0 && i < objp->io_vecs.count; ++i) {
        size_t buff_len = P_MIN(len, objp->io_vecs.iovecs[i].iov_len);
        if (!xdrdrec_direct_write(xdrs, (caddr_t)objp->io_vecs.iovecs[i].iov_base, buff_len, buff_len == len)) {
            return FALSE;
        }
        len -= buff_len;
    }
    return TRUE;
}

bool_t
xdr_buffered_READ3res(XDR *xdrs, BufferedREAD3res *objp)
{
    if (!xdr_nfsstat3 (xdrs, &objp->status))
        return FALSE;
    switch (objp->status) {
        case NFS3_OK:
            if (!xdr_buffered_READ3resok (xdrs, &objp->READ3res_u.resok))
                return FALSE;
            break;
        default:
            if (!xdr_READ3resfail (xdrs, &objp->READ3res_u.resfail))
                return FALSE;
            break;
    }
    return TRUE;
}

bool_t
xdr_READ3free(XDR *xdrs, READ3args *args, BufferedREAD3res *res)
{
    Rpc *rpc = (Rpc *)xdrs->x_public;
    free_iovec(&res->READ3res_u.resok.alloc_vecs, rpc);
    return TRUE;
}

void NfsServer::set_xdr_procs(RpcRequest *request)
{
    request->args_proc = nullptr;
    request->res_proc = nullptr;
    request->free_proc = nullptr;

    // Sets the pointers to the xdrproc_t parameters according to the requested procedure.
    // In addition if the request arguments / result structure contain dynamic arguments it sets the pointers in
    // order to avoid dynamic memory allocation by XDR.
    // The pointers are set to memory within the args_buffer / res_buffer members.
    switch (request->msg.body.vrpc_msg_body_u.cbody.proc) {
        case NFSPROC3_NULL:
            request->args_proc = (xdrproc_t)xdr_void;
            request->res_proc = (xdrproc_t)xdr_void;
            break;

        case NFSPROC3_GETATTR:
            request->args.getattr.object.data.data_val = request->args_buffer;
            request->args_proc = (xdrproc_t)xdr_GETATTR3args;
            request->res_proc = (xdrproc_t)xdr_GETATTR3res;
            break;

        case NFSPROC3_SETATTR:
            request->args.setattr.object.data.data_val = request->args_buffer;
            request->args_proc = (xdrproc_t)xdr_SETATTR3args;
            request->res_proc = (xdrproc_t)xdr_SETATTR3res;
            break;

        case NFSPROC3_LOOKUP:
            request->args.lookup.what.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->args.lookup.what.name = request->args_buffer_nfs.name0;
            request->res.lookup.LOOKUP3res_u.resok.object.data.data_val = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_LOOKUP3args;
            request->res_proc = (xdrproc_t)xdr_LOOKUP3res;
            break;

        case NFSPROC3_ACCESS:
            request->args.access.object.data.data_val = request->args_buffer;
            request->args_proc = (xdrproc_t)xdr_ACCESS3args;
            request->res_proc = (xdrproc_t)xdr_ACCESS3res;
            break;

        case NFSPROC3_READLINK:
            request->args.readlink.symlink.data.data_val = request->args_buffer;
            request->res.readlink.READLINK3res_u.resok.data = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_READLINK3args;
            request->res_proc = (xdrproc_t)xdr_READLINK3res;
            break;

        case NFSPROC3_READ:
            request->args.read.file.data.data_val = request->args_buffer;
            request->res.read.READ3res_u.resok.io_vecs.iovecs = (P::IO::IOVec *)request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_READ3args;
            request->res_proc = (xdrproc_t)xdr_buffered_READ3res;
            request->free_proc = (xdrproc_t)xdr_READ3free;
            break;

        case NFSPROC3_WRITE:
            request->args.write.file.data.data_val = request->args_buffer_nfs_with_4k.fh;
            request->args.write.io_vecs.iovecs = (P::IO::IOVec *)(request->args_buffer_nfs_with_4k._4k);
            request->args_proc = (xdrproc_t)xdr_buffered_WRITE3args;
            request->res_proc = (xdrproc_t)xdr_WRITE3res;
            break;

        case NFSPROC3_CREATE:
            request->args.create.where.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->args.create.where.name = request->args_buffer_nfs.name0;
            request->res.create.CREATE3res_u.resok.obj.post_op_fh3_u.handle.data.data_val = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_CREATE3args;
            request->res_proc = (xdrproc_t)xdr_CREATE3res;
            break;

        case NFSPROC3_MKDIR:
            request->args.mkdir.where.name = request->args_buffer_nfs.name0;
            request->args.mkdir.where.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->res.mkdir.MKDIR3res_u.resok.obj.post_op_fh3_u.handle.data.data_val = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_MKDIR3args;
            request->res_proc = (xdrproc_t)xdr_MKDIR3res;
            break;

        case NFSPROC3_SYMLINK:
            request->args.symlink.where.dir.data.data_val = request->args_buffer_nfs_with_4k.fh;
            request->args.symlink.where.name = request->args_buffer_nfs_with_4k.name;
            request->args.symlink.symlink.symlink_data = request->args_buffer_nfs_with_4k._4k;
            request->res.symlink.SYMLINK3res_u.resok.obj.post_op_fh3_u.handle.data.data_val = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_SYMLINK3args;
            request->res_proc = (xdrproc_t)xdr_SYMLINK3res;
            break;

        case NFSPROC3_MKNOD:
            request->args.mknod.where.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->args.mknod.where.name = request->args_buffer_nfs.name0;
            request->res.mknod.MKNOD3res_u.resok.obj.post_op_fh3_u.handle.data.data_val = request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_MKNOD3args;
            request->res_proc = (xdrproc_t)xdr_MKNOD3res;
            break;

        case NFSPROC3_REMOVE:
            request->args.remove.object.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->args.remove.object.name = request->args_buffer_nfs.name0;
            request->args_proc = (xdrproc_t)xdr_REMOVE3args;
            request->res_proc = (xdrproc_t)xdr_REMOVE3res;
            break;

        case NFSPROC3_RMDIR:
            request->args.rmdir.object.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->args.rmdir.object.name = request->args_buffer_nfs.name0;
            request->args_proc = (xdrproc_t)xdr_RMDIR3args;
            request->res_proc = (xdrproc_t)xdr_RMDIR3res;
            break;

        case NFSPROC3_RENAME:
            request->args.rename.fromfile.dir.data.data_val = request->args_buffer_nfs.fh0;
            request->args.rename.fromfile.name = request->args_buffer_nfs.name0;
            request->args.rename.tofile.dir.data.data_val = request->args_buffer_nfs.fh1;
            request->args.rename.tofile.name = request->args_buffer_nfs.name1;
            request->args_proc = (xdrproc_t)xdr_RENAME3args;
            request->res_proc = (xdrproc_t)xdr_RENAME3res;
            break;

        case NFSPROC3_LINK:
            request->args.link.file.data.data_val = request->args_buffer_nfs.fh0;
            request->args.link.link.dir.data.data_val = request->args_buffer_nfs.fh1;
            request->args.link.link.name = request->args_buffer_nfs.name0;
            request->args_proc = (xdrproc_t)xdr_LINK3args;
            request->res_proc = (xdrproc_t)xdr_LINK3res;
            break;

        case NFSPROC3_READDIR:
            request->args.readdir.dir.data.data_val = request->args_buffer;
            request->res.readdir.READDIR3res_u.resok.reply.entries = (entry3 *)request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_READDIR3args;
            request->res_proc = (xdrproc_t)xdr_READDIR3res;
            break;

        case NFSPROC3_READDIRPLUS:
            request->args.readdirplus.dir.data.data_val = request->args_buffer;
            request->res.readdirplus.READDIRPLUS3res_u.resok.reply.entries = (entryplus3 *)request->res_buffer;
            request->args_proc = (xdrproc_t)xdr_READDIRPLUS3args;
            request->res_proc = (xdrproc_t)xdr_READDIRPLUS3res;
            break;

        case NFSPROC3_FSSTAT:
            request->args.fsstat.fsroot.data.data_val = request->args_buffer;
            request->args_proc = (xdrproc_t)xdr_FSSTAT3args;
            request->res_proc = (xdrproc_t)xdr_FSSTAT3res;
            break;

        case NFSPROC3_FSINFO:
            request->args_proc = (xdrproc_t)xdr_FSINFO3args;
            request->res_proc = (xdrproc_t)xdr_FSINFO3res;
            break;

        case NFSPROC3_PATHCONF:
            request->args_proc = (xdrproc_t)xdr_PATHCONF3args;
            request->res_proc = (xdrproc_t)xdr_PATHCONF3res;
            break;

        case NFSPROC3_COMMIT:
            request->args.commit.file.data.data_val = request->args_buffer;
            request->args_proc = (xdrproc_t)xdr_COMMIT3args;
            request->res_proc = (xdrproc_t)xdr_COMMIT3res;
            break;

        default:
            PT_WARN(DATA, "proc not found");
            request->status = RpcStatus::PROC_NOT_FOUND;
            break;
    }
}

void NfsServer::run_procedure(RpcRequest *request)
{
    switch (request->msg.body.vrpc_msg_body_u.cbody.proc) {
        case NFSPROC3_NULL:
            break;

        case NFSPROC3_GETATTR:
            this->get_attr(request, &request->args.getattr, &request->res.getattr);
            break;

        case NFSPROC3_SETATTR:
            this->set_attr(request, &request->args.setattr, &request->res.setattr);
            break;

        case NFSPROC3_LOOKUP:
            this->lookup(request, &request->args.lookup, &request->res.lookup);
            break;

        case NFSPROC3_ACCESS:
            this->access(request, &request->args.access, &request->res.access);
            break;

        case NFSPROC3_READLINK:
            this->readlink(request, &request->args.readlink, &request->res.readlink);
            break;

        case NFSPROC3_READ:
            this->read(request, &request->args.read, &request->res.read);
            break;

        case NFSPROC3_WRITE:
            this->write(request, &request->args.write, &request->res.write);
            break;

        case NFSPROC3_CREATE:
            this->create(request, &request->args.create, &request->res.create);
            break;

        case NFSPROC3_MKDIR:
            this->mkdir(request, &request->args.mkdir, &request->res.mkdir);
            break;

        case NFSPROC3_SYMLINK:
            this->symlink(request, &request->args.symlink, &request->res.symlink);
            break;

        case NFSPROC3_MKNOD:
            this->mknod(request, &request->args.mknod, &request->res.mknod);
            break;

        case NFSPROC3_REMOVE:
            this->remove(request, &request->args.remove, &request->res.remove);
            break;

        case NFSPROC3_RMDIR:
            this->rmdir(request, &request->args.rmdir, &request->res.rmdir);
            break;

        case NFSPROC3_RENAME:
            this->rename(request, &request->args.rename, &request->res.rename);
            break;

        case NFSPROC3_LINK:
            this->link(request, &request->args.link, &request->res.link);
            break;

        case NFSPROC3_READDIR:
            this->readdir(request, &request->args.readdir, &request->res.readdir);
            break;

        case NFSPROC3_READDIRPLUS:
            this->readdir_plus(request, &request->args.readdirplus, &request->res.readdirplus);
            break;

        case NFSPROC3_FSSTAT:
            this->fsstat(request, &request->args.fsstat, &request->res.fsstat);
            break;

        case NFSPROC3_FSINFO:
            this->fsinfo(request, &request->args.fsinfo, &request->res.fsinfo);
            break;

        case NFSPROC3_PATHCONF:
            this->pathconf(request, &request->args.pathconf, &request->res.pathconf);
            break;

        case NFSPROC3_COMMIT:
            this->commit(request, &request->args.commit, &request->res.commit);
            break;

        default:
            PT_WARN(DATA, "proc not found");
            request->status = RpcStatus::PROC_NOT_FOUND;
            return;
    }

}

static bool is_gid_in_request(RpcRequest *request, uint32_t gid)
{
    if (gid == request->auth_params.gid) {
        return true;
    }
    LOOP(request->auth_params.gids.gids_len, i) {
        if (request->auth_params.gids.gids_val[i] == gid) {
            return true;
        }
    }
    return false;
}

static void access_check(RpcRequest *request, EStore::SystemAttr *attr, uint32_t required_mode, uint32_t *granted_mode)
{
    uint32_t element_uid = attr->uid;
    uint32_t element_gid = attr->gid;
    uint32_t element_mode = attr->mode;
    uint32_t caller_uid = request->auth_params.uid;

    PT_DEBUG(DATA, "element_mode=%o element_uid=%u element_uid=%u caller_uid=%u caller_gid=%u required_mode=%o",
           element_mode, element_uid, element_uid, caller_uid, request->auth_params.gid, required_mode);

    // caller is root
    if (caller_uid == 0) {
        if (attr->element_flags & (uint64_t)ElementFlags::DIR) {
            // if its a directory root can do whatever it wants
            *granted_mode = required_mode;
            PT_DEBUG(DATA, "required_mode=%o granted_mode=%o", required_mode, *granted_mode);
            return;
        }
        if (required_mode & EXEC_MODE && !(element_mode & (S_IXOTH | S_IXUSR | S_IXGRP))) {
            // root can execute only if the file is an executable
            *granted_mode = required_mode & ~EXEC_MODE;
        } else {
            *granted_mode = required_mode;
        }
        PT_DEBUG(DATA, "required_mode=%o granted_mode=%o", required_mode, *granted_mode);
        return;
    }

    // decide which mode bits to use, required mode uses the LSB bits so shift the element mode bits according the the
    // file owner / group is order to align the required mode to the relevant part of the element mode
    if (caller_uid == element_uid) {
        // use owner bits
        element_mode >>= 6;
    } else if (is_gid_in_request(request, element_gid)) {
        // use group bits
        element_mode >>= 3;
    }
    // if caller is not owner / in group the other bits will be used

    *granted_mode = required_mode & element_mode;
    PT_DEBUG(DATA, "required_mode=%o granted_mode=%o", required_mode, *granted_mode);
}

struct AccessCheckCtx {
    RpcRequest *request;
    uint32_t required_mode;
};

EStoreRes access_check_cb(SystemAttr *attr, void *ctx)
{
    AccessCheckCtx *check_ctx = (AccessCheckCtx *)ctx;
    uint32_t granted_mode = 0;
    access_check(check_ctx->request, attr, check_ctx->required_mode, &granted_mode);
    if (granted_mode != check_ctx->required_mode) {
        PT_DEBUG(DATA, "rejecting request");
        return EStoreRes::PERM_ERROR;
    }
    return EStoreRes::OK;
}

static EStoreRes read_check_cb(SystemAttr *attr, void *ctx)
{
    AccessCheckCtx *check_ctx = (AccessCheckCtx *)ctx;
    uint32_t granted_mode = 0;
    // since executing a file over NFS requires reading it, access is allowed in case the user is
    // allowed to read or execute
    access_check(check_ctx->request, attr, READ_MODE | EXEC_MODE, &granted_mode);
    if (granted_mode == 0) {
        PT_DEBUG(DATA, "rejecting request");
        return EStoreRes::PERM_ERROR;
    }
    return EStoreRes::OK;
}

static EStoreRes write_check_cb(SystemAttr *attr, void *ctx)
{
    AccessCheckCtx *check_ctx = (AccessCheckCtx *)ctx;
    RpcRequest *request = check_ctx->request;
    uint32_t granted_mode = 0;
    // since a file owner can change the mode while keeping the file open, the owner of a file can access it
    // regardless of the permission setting.
    if (attr->uid == request->auth_params.uid) {
        PT_DEV(DATA, "allowing owner to write");
        return EStoreRes::OK;
    }

    access_check(check_ctx->request, attr, WRITE_MODE, &granted_mode);
    if (granted_mode != WRITE_MODE) {
        PT_DEBUG(DATA, "rejecting request");
        return EStoreRes::PERM_ERROR;
    }
    return EStoreRes::OK;
}

static EStoreRes setattr_check_cb(SystemAttr *attr, void *ctx)
{
    AccessCheckCtx *check_ctx = (AccessCheckCtx *)ctx;
    RpcRequest *request = check_ctx->request;
    uint32_t element_uid = attr->uid;
    uint32_t caller_uid = request->auth_params.uid;
    uint32_t required_mode = 0;

    if (caller_uid == 0) {
        // root can do whatever it wants
        return EStoreRes::OK;
    }

    bool is_owner = (caller_uid == element_uid);
    sattr3 *new_attr = &request->args.setattr.new_attributes;

    // only ownership change need to be checked for owner
    if (new_attr->uid.set_it == TRUE) {
        if (!is_owner) {
            PT_DEBUG(DATA, "regular user is only allowed to chown to itself");
            return EStoreRes::PERM_ERROR;
        }
    }
    if (new_attr->gid.set_it == TRUE) {
        if (!is_gid_in_request(request, new_attr->gid.set_gid3_u.gid)) {
            PT_DEBUG(DATA, "regular user can change group owner only to a group it is a member of");
            return EStoreRes::PERM_ERROR;
        }
    }

    // any attribute after this is always changeable by the owner.
    if (is_owner) {
        return EStoreRes::OK;
    }

    // only owner / root may change mode
    if (new_attr->mode.set_it == TRUE) {
        return EStoreRes::PERM_ERROR;
    }

    // changing size requires owner or write permission
    if (new_attr->size.set_it == TRUE) {
        required_mode |= WRITE_MODE;
    }

    // changing time requires owner or write permission
    if (new_attr->atime.set_it != DONT_CHANGE || new_attr->mtime.set_it != DONT_CHANGE) {
        required_mode |= WRITE_MODE;
    }

    if (required_mode != 0) {
        check_ctx->required_mode = required_mode;
        return access_check_cb(attr, ctx);
    }
    return EStoreRes::OK;
}


void NfsServer::get_attr(RpcRequest *request, GETATTR3args *args, GETATTR3res *res)
{
    res->status = NFS3_OK;
    // getting an element attributes don't require any permissions
    EStoreRes eres = get_attr_from_fh3(&args->object, &res->GETATTR3res_u.resok.obj_attributes);
    if (eres != EStoreRes::OK) {
        res->status = eres_to_nfs_status(eres);
        return;
    }
}

void NfsServer::set_attr(RpcRequest *request, SETATTR3args *args, SETATTR3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->object, &handle);
    PT_DEBUG(DATA, "setattr on handle=%lx", handle);

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = 0,
    };

    SettableAttr sattr;
    nfs_sattr_to_settable_attr(&args->new_attributes, &sattr);
    SystemAttr pre_attr;
    SystemAttr post_attr;
    uint64_t ctime_guard = 0;
    if (args->guard.check == TRUE) {
        ctime_guard = SEC_TO_NANO(args->guard.sattrguard3_u.obj_ctime.seconds) +
                      args->guard.sattrguard3_u.obj_ctime.nseconds;
    }
    res->status = NFS3_OK;
    EStoreRes eres = _estore->set_attr(setattr_check_cb, &check_ctx, handle, &sattr, ctime_guard,
                                       nullptr, nullptr, &pre_attr, &post_attr);
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "setattr on handle=%lx failed res=%d", handle, eres);
        res->status = eres_to_nfs_status(eres);
        res->SETATTR3res_u.resfail.obj_wcc.after.attributes_follow = FALSE;
        res->SETATTR3res_u.resfail.obj_wcc.before.attributes_follow = FALSE;
        return;
    }
    fill_wcc_data(&res->SETATTR3res_u.resok.obj_wcc, &pre_attr, &post_attr);
}

void NfsServer::lookup(RpcRequest *request, LOOKUP3args *args, LOOKUP3res *res)
{
    EHandle phandle;
    nfs_handle_to_ehandle(&args->what.dir, &phandle);
    PT_DEBUG(DATA, "lookup handle=%lx name=%s", phandle, args->what.name);
    EHandle ehandle;
    SystemAttr eattr;
    SystemAttr pattr;
    res->status = NFS3_OK;
    EStoreRes eres;

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = EXEC_MODE,
    };

    if (strncmp(args->what.name, ".", NAME_MAX) == 0) {
        eres = _estore->get_attr(nullptr, nullptr, phandle, &eattr, nullptr, nullptr);
        memcpy(&pattr, &eattr, sizeof(pattr));
        ehandle = phandle;
    } else if (strncmp(args->what.name, "..", NAME_MAX) == 0) {
        eres = _estore->lookup_parent(access_check_cb, &check_ctx, phandle, &ehandle, &eattr, &pattr);
    } else {
        eres = _estore->lookup(access_check_cb, &check_ctx, phandle, args->what.name, true, &ehandle, &eattr, &pattr);
    }
    if (eres != EStoreRes::OK) {
        PT_DEBUG(DATA, "lookup failed eres=%d", eres);
        res->status = eres_to_nfs_status(eres);
        res->LOOKUP3res_u.resfail.dir_attributes.attributes_follow = FALSE;
        return;
    }
    ehandle_to_nfs_handle(ehandle, &res->LOOKUP3res_u.resok.object);
    res->LOOKUP3res_u.resok.obj_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&eattr, &res->LOOKUP3res_u.resok.obj_attributes.post_op_attr_u.attributes);
    res->LOOKUP3res_u.resok.dir_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&pattr, &res->LOOKUP3res_u.resok.dir_attributes.post_op_attr_u.attributes);
}

void NfsServer::access(RpcRequest *request, ACCESS3args *args, ACCESS3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->object, &handle);
    PT_DEBUG(DATA, "access check handle=%lx requested access=%x", handle, args->access);

    SystemAttr sys_attr;
    res->status = NFS3_OK;
    EStoreRes eres = _estore->get_attr(nullptr, nullptr, handle, &sys_attr, nullptr, nullptr);
    if (eres != EStoreRes::OK) {
        res->status = eres_to_nfs_status(eres);
        res->ACCESS3res_u.resfail.obj_attributes.attributes_follow = FALSE;
        return;
    }

    bool is_dir = sys_attr.element_flags & (uint64_t)ElementFlags::DIR;
    uint32_t requested_access = args->access;
    uint32_t required_mode;
    nfs_access_to_mode(is_dir, &requested_access, &required_mode);
    uint32_t granted_mode = 0;
    access_check(request, &sys_attr, required_mode, &granted_mode);
    uint32_t granted_access = 0;
    mode_to_nfs_access(granted_mode, &granted_access);
    granted_access &= requested_access;
    PT_DEBUG(DATA, "access check handle=%lx requested_access=%x granted_access=%x", handle, args->access, granted_access);

    res->ACCESS3res_u.resok.access = granted_access;
    res->ACCESS3res_u.resok.obj_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&sys_attr, &res->ACCESS3res_u.resok.obj_attributes.post_op_attr_u.attributes);
}

void NfsServer::readlink(RpcRequest *request, READLINK3args *args, READLINK3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->symlink, &handle);
    PT_DEBUG(DATA, "readlink handle=%lx", handle);

    // symlink data is stored as an extended attribute
    SystemAttr sys_attr;
    char xattr_buffer[PATH_MAX];
    ExtendedAttrs proto_xattr;
    proto_xattr.buff = xattr_buffer;
    proto_xattr.buff_size = sizeof(xattr_buffer);
    res->status = NFS3_OK;
    EStoreRes eres = _estore->get_attr(nullptr, nullptr, handle, &sys_attr, nullptr, &proto_xattr);
    if (eres == EStoreRes::OK) {
        bool found = false;
        LOOP(proto_xattr.n_attrs, i) {
            ExtendedAttr *xattr = &proto_xattr.attrs[i];
            if (strcmp(xattr->name, SYMLINK_XATTR) == 0) {
                strncpy(res->READLINK3res_u.resok.data, (const char *)xattr->val, xattr->val_size);
                found = true;
                break;
            }
        }
        if (!found) {
            eres = EStoreRes::INVAL;
        }
    }
    if (eres != EStoreRes::OK) {
        res->status = eres_to_nfs_status(eres);
        res->READLINK3res_u.resfail.symlink_attributes.attributes_follow = FALSE;
        return;
    }
    res->READLINK3res_u.resok.symlink_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&sys_attr, &res->READLINK3res_u.resok.symlink_attributes.post_op_attr_u.attributes);
}

void NfsServer::read(RpcRequest *request, READ3args *args, BufferedREAD3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->file, &handle);
    PT_DEBUG(DATA, "read from handle=%lx offset=%lu count=%u", handle, args->offset, args->count);

    P::IO::IOVecs *io_vecs = &res->READ3res_u.resok.io_vecs;
    io_vecs->count = (uint32_t)ceil((double)args->count / EStore::DATA_BUFFER_SIZE);

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = READ_MODE | EXEC_MODE,
    };
    SystemAttr pre_attr;
    SystemAttr post_attr;
    res->status = NFS3_OK;
    EStoreRes eres = _estore->read(read_check_cb, &check_ctx, handle, args->offset, args->count,
                                   &res->READ3res_u.resok.io_vecs, &res->READ3res_u.resok.alloc_vecs,
                                   &res->READ3res_u.resok.count, (bool *)&res->READ3res_u.resok.eof,
                                   &pre_attr, &post_attr);
    if (eres != EStoreRes::OK) {
        res->status = eres_to_nfs_status(eres);
        PT_ERROR(DATA, "read from handle=%lx offset=%lu count=%u failed res->status=%d",
                 handle, args->offset, args->count, res->status);
        res->READ3res_u.resfail.file_attributes.attributes_follow = FALSE;
        return;
    }
    res->READ3res_u.resok.data_len = res->READ3res_u.resok.count;
    res->READ3res_u.resok.file_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&post_attr, &res->READ3res_u.resok.file_attributes.post_op_attr_u.attributes);
}

void NfsServer::write(RpcRequest *request, BufferedWRITE3args *args, WRITE3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->file, &handle);
    PT_DEBUG(DATA, "write to handle=%lx offset=%lu count=%u", handle, args->offset, args->count);

    if (args->count != args->data_len) {
        res->status = NFS3ERR_INVAL;
        res->WRITE3res_u.resfail.file_wcc.after.attributes_follow = FALSE;
        res->WRITE3res_u.resfail.file_wcc.before.attributes_follow = FALSE;
    }

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    SystemAttr pre_attr;
    SystemAttr post_attr;
    res->status = NFS3_OK;
    EStoreRes eres = _estore->write(write_check_cb, &check_ctx, handle, args->offset, &args->io_vecs, &pre_attr, &post_attr);
    if (eres != EStoreRes::OK) {
        PT_DEBUG(DATA, "write handle=%lx offset=%lu count=%u failed res=%d", handle, args->offset, args->count, eres);
        res->status = eres_to_nfs_status(eres);
        res->WRITE3res_u.resfail.file_wcc.after.attributes_follow = FALSE;
        res->WRITE3res_u.resfail.file_wcc.before.attributes_follow = FALSE;
        return;
    }
    fill_wcc_data(&res->WRITE3res_u.resok.file_wcc, &pre_attr, &post_attr);
    // estore always commits the data
    res->WRITE3res_u.resok.committed = FILE_SYNC;
    res->WRITE3res_u.resok.count = args->count;
    memset(res->WRITE3res_u.resok.verf, 0, sizeof(res->WRITE3res_u.resok.verf));
}

void NfsServer::create(RpcRequest *request, CREATE3args *args, CREATE3res *res)
{
    EHandle phandle;
    nfs_handle_to_ehandle(&args->where.dir, &phandle);
    PT_DEBUG(DATA, "create phandle=%lx name=%s", phandle, args->where.name);
    
    CreateFlags flags = CreateFlags::HAS_DATA;
    if (args->how.mode == GUARDED || args->how.mode == EXCLUSIVE) {
        SET_ENUM_FLAG(flags, CreateFlags, DONT_OVERWRITE);
    }
    uint64_t verifier = 0;
    SettableAttr settable_attr;
    settable_attr.flags = AttrFlag::NONE;
    if (args->how.mode == EXCLUSIVE) {
        memcpy(&verifier, args->how.createhow3_u.verf, sizeof(verifier));
    } else {
        nfs_sattr_to_settable_attr(&args->how.createhow3_u.obj_attributes, &settable_attr);
    }
    set_owner_from_auth(&settable_attr, request);
    SET_ENUM_FLAG(settable_attr.flags, AttrFlag, ELEMENT_FLAGS);
    settable_attr.element_flags = (uint64_t)ElementFlags::FILE;

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    EHandle ehandle;
    SystemAttr element_attr;
    SystemAttr pre_pattr;
    SystemAttr post_pattr;
    EStoreRes eres = _estore->create(access_check_cb, &check_ctx, phandle, args->where.name, flags, verifier, &settable_attr,
                                     nullptr, nullptr, &ehandle, &element_attr, &pre_pattr, &post_pattr);
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "create phandle=%lx name=%s failed res=%d", phandle, args->where.name, eres);
        res->status = eres_to_nfs_status(eres);
        res->CREATE3res_u.resfail.dir_wcc.after.attributes_follow = FALSE;
        res->CREATE3res_u.resfail.dir_wcc.before.attributes_follow = FALSE;
        return;
    }

    res->status = NFS3_OK;
    fill_create_resok(&res->CREATE3res_u.resok, ehandle, element_attr, pre_pattr, post_pattr);
}

void NfsServer::mkdir(RpcRequest *request, MKDIR3args *args, MKDIR3res *res)
{
    EHandle phandle;
    nfs_handle_to_ehandle(&args->where.dir, &phandle);
    PT_DEBUG(DATA, "mkdir phandle=%lx name=%s", phandle, args->where.name);

    CreateFlags flags = CreateFlags::HAS_CHILDREN;
    SettableAttr settable_attr;
    nfs_sattr_to_settable_attr(&args->attributes, &settable_attr);
    set_owner_from_auth(&settable_attr, request);
    SET_ENUM_FLAG(settable_attr.flags, AttrFlag, ELEMENT_FLAGS);
    settable_attr.element_flags = (uint64_t)ElementFlags::DIR;

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    EHandle ehandle;
    SystemAttr element_attr;
    SystemAttr pre_pattr;
    SystemAttr post_pattr;
    EStoreRes eres = _estore->create(access_check_cb, &check_ctx, phandle, args->where.name, flags, 0, &settable_attr,
                                     nullptr, nullptr, &ehandle, &element_attr, &pre_pattr, &post_pattr);
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "mkdir phandle=%lx name=%s failed res=%d", phandle, args->where.name, eres);
        res->status = eres_to_nfs_status(eres);
        res->MKDIR3res_u.resfail.dir_wcc.before.attributes_follow = FALSE;
        res->MKDIR3res_u.resfail.dir_wcc.after.attributes_follow = FALSE;
        return;
    }

    res->status = NFS3_OK;
    fill_create_resok((CREATE3resok *)&res->MKDIR3res_u.resok, ehandle, element_attr, pre_pattr, post_pattr);
}

void NfsServer::symlink(RpcRequest *request, SYMLINK3args *args, SYMLINK3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->where.dir, &handle);
    PT_DEBUG(DATA, "symlink handle=%lx name=%s symlink=%s", handle, args->where.name, args->symlink.symlink_data);

    // estore does not know about symlink, instead we create an empty element and use an extended attribute in order
    // to store the link data
    CreateFlags flags = CreateFlags::NONE_CREATE_FLAGS;
    SettableAttr settable_attr;
    nfs_sattr_to_settable_attr(&args->symlink.symlink_attributes, &settable_attr);
    set_owner_from_auth(&settable_attr, request);
    SET_ENUM_FLAG(settable_attr.flags, AttrFlag, ELEMENT_FLAGS);
    settable_attr.element_flags = (uint64_t)ElementFlags::SYMLINK;

    ExtendedAttrs xattrs;
    xattrs.n_attrs = 1;
    ExtendedAttr *xattr = &xattrs.attrs[0];
    xattr->name = (char *)SYMLINK_XATTR;
    xattr->val_size = (uint32_t)(strlen(args->symlink.symlink_data) + 1);
    xattr->val = args->symlink.symlink_data;

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    EHandle ehandle;
    SystemAttr element_attr;
    SystemAttr pre_pattr;
    SystemAttr post_pattr;
    EStoreRes eres = _estore->create(access_check_cb, &check_ctx, handle, args->where.name, flags, 0, &settable_attr,
                                     nullptr, &xattrs, &ehandle, &element_attr, &pre_pattr, &post_pattr);
    if (eres != EStoreRes::OK) {
        PT_DEBUG(DATA, "symlink handle=%lx name=%s symlink=%s failed res=%d",
                 handle, args->where.name, args->symlink.symlink_data, eres);
        res->status = eres_to_nfs_status(eres);
        res->SYMLINK3res_u.resfail.dir_wcc.before.attributes_follow = FALSE;
        res->SYMLINK3res_u.resfail.dir_wcc.after.attributes_follow = FALSE;
        return;
    }

    res->status = NFS3_OK;
    fill_create_resok((CREATE3resok *)&res->SYMLINK3res_u.resok, ehandle, element_attr, pre_pattr, post_pattr);
}

void NfsServer::mknod(RpcRequest *request, MKNOD3args *args, MKNOD3res *res)
{
    EHandle phandle;
    nfs_handle_to_ehandle(&args->where.dir, &phandle);
    // not supported
    PT_DEBUG(DATA, "mknod phandle=%lx name=%s, not supported returning error", phandle, args->where.name);

    res->status = NFS3ERR_NOTSUPP;
    res->MKNOD3res_u.resfail.dir_wcc.before.attributes_follow = FALSE;
    res->MKNOD3res_u.resfail.dir_wcc.after.attributes_follow = FALSE;
}

void NfsServer::unlink(RpcRequest *request, diropargs3 *args, nfsstat3 *status, wcc_data *resok, wcc_data *resfail)
{
    EHandle phandle;
    nfs_handle_to_ehandle(&args->dir, &phandle);
    PT_DEBUG(DATA, "unlink phandle=%lx name=%s", phandle, args->name);

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    SystemAttr pre_attr;
    SystemAttr post_attr;
    *status = NFS3_OK;
    EStoreRes eres = _estore->unlink(access_check_cb, &check_ctx, phandle, args->name, true, &pre_attr, &post_attr);
    if (eres != EStoreRes::OK) {
        resfail->before.attributes_follow = FALSE;
        resfail->after.attributes_follow = FALSE;
        *status = eres_to_nfs_status(eres);
        PT_ERROR(DATA, "unlink phandle=%lx name=%s res=%d", phandle, args->name, eres);
        return;
    }
    fill_wcc_data(resok, &pre_attr, &post_attr);
}

void NfsServer::remove(RpcRequest *request, REMOVE3args *args, REMOVE3res *res)
{
    unlink(request, &args->object, &res->status, &res->REMOVE3res_u.resok.dir_wcc, &res->REMOVE3res_u.resfail.dir_wcc);
}

void NfsServer::rmdir(RpcRequest *request, RMDIR3args *args, RMDIR3res *res)
{
    unlink(request, &args->object, &res->status, &res->RMDIR3res_u.resok.dir_wcc, &res->RMDIR3res_u.resfail.dir_wcc);
}

void NfsServer::fill_wcc_data(wcc_data *wcc_data, EStore::SystemAttr *pre_attr, EStore::SystemAttr *post_attr)
{
    wcc_data->before.attributes_follow = TRUE;
    sys_attr_to_wcc_attr(pre_attr, &wcc_data->before.pre_op_attr_u.attributes);
    wcc_data->after.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(post_attr, &wcc_data->after.post_op_attr_u.attributes);
}

void NfsServer::rename(RpcRequest *request, RENAME3args *args, RENAME3res *res)
{
    EHandle from_handle;
    EHandle to_handle;
    nfs_handle_to_ehandle(&args->fromfile.dir, &from_handle);
    nfs_handle_to_ehandle(&args->tofile.dir, &to_handle);
    PT_DEBUG(DATA, "rename from handle=%lx name=%s to handle=%lx name=%s", from_handle, args->fromfile.name,
           to_handle, args->tofile.name);

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    SystemAttr pre_src_attr;
    SystemAttr post_src_attr;
    SystemAttr pre_dst_attr;
    SystemAttr post_dst_attr;
    res->status = NFS3_OK;
    EStoreRes eres = _estore->rename(access_check_cb, &check_ctx, from_handle, args->fromfile.name, to_handle, args->tofile.name,
                                     &pre_src_attr, &post_src_attr, &pre_dst_attr, &post_dst_attr);
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "rename from handle=%lx name=%s to handle=%lx name=%s failed res=%d", from_handle, args->fromfile.name,
                 to_handle, args->tofile.name, eres);
        res->status = eres_to_nfs_status(eres);
        res->RENAME3res_u.resfail.fromdir_wcc.after.attributes_follow = FALSE;
        res->RENAME3res_u.resfail.fromdir_wcc.before.attributes_follow = FALSE;
        res->RENAME3res_u.resfail.todir_wcc.after.attributes_follow = FALSE;
        res->RENAME3res_u.resfail.todir_wcc.before.attributes_follow = FALSE;
        return;
    }
    fill_wcc_data(&res->RENAME3res_u.resok.todir_wcc, &pre_src_attr, &post_src_attr);
    fill_wcc_data(&res->RENAME3res_u.resok.fromdir_wcc, &pre_dst_attr, &post_dst_attr);
}

void NfsServer::link(RpcRequest *request, LINK3args *args, LINK3res *res)
{
    EHandle target_handle;
    nfs_handle_to_ehandle(&args->file, &target_handle);
    EHandle phandle;
    nfs_handle_to_ehandle(&args->link.dir, &phandle);
    PT_DEBUG(DATA, "link from phandle=%lx name=%s to target_handle=%lx", phandle, args->link.name, target_handle);

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = WRITE_MODE,
    };
    res->status = NFS3_OK;
    SystemAttr post_link_attr;
    SystemAttr pre_pattr;
    SystemAttr post_pattr;
    EStoreRes eres = _estore->link(access_check_cb, &check_ctx, target_handle, phandle, args->link.name,
                                   &post_link_attr, &pre_pattr, &post_pattr);
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "link from phandle=%lx name=%s to target_handle=%lx failed res=%d",
                 phandle, args->link.name, target_handle, eres);
        res->status = eres_to_nfs_status(eres);
        res->LINK3res_u.resfail.file_attributes.attributes_follow = FALSE;
        res->LINK3res_u.resfail.linkdir_wcc.before.attributes_follow = FALSE;
        res->LINK3res_u.resfail.linkdir_wcc.after.attributes_follow = FALSE;
        return;
    }
    res->LINK3res_u.resok.file_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&post_link_attr, &res->LINK3res_u.resok.file_attributes.post_op_attr_u.attributes);
    fill_wcc_data(&res->LINK3res_u.resok.linkdir_wcc, &pre_pattr, &post_pattr);
}

static bool readdir_cb(EStore::ListEntry *entry, void *ctx)
{
    ReaddirState *rd_state = (ReaddirState *)ctx;
    PT_DEBUG(DATA, "add entry handle=%lx name=%s dir_mem_left=%lu mem_left=%lu", entry->handle, entry->name,
           rd_state->dir_mem_left, rd_state->mem_left);
    rd_state->last_retval = false;
    // check if we have dir space left to store the name and file id (dir space only relates to directory information)
    uint64_t name_len = strnlen(entry->name, PATH_MAX) + 1;

    // check if we have we have space to store the entry
    uint64_t required_space = name_len + sizeof(entry3);
    if (rd_state->mem_left < required_space) {
        return false;
    }
    rd_state->mem_left -= required_space;

    // move to the next entry
    if (rd_state->rd_entry != nullptr) {
        rd_state->rd_entry->nextentry = (entry3 *)rd_state->next_entry;
        rd_state->rd_entry = rd_state->rd_entry->nextentry;
    } else {
        // first entry
        rd_state->rd_entry = (entry3 *)rd_state->next_entry;
    }
    // fill the entry values
    entry3 *rd_entry = rd_state->rd_entry;
    rd_entry->nextentry = nullptr;

    rd_entry->cookie = entry->offset;
    rd_entry->fileid = entry->handle;

    rd_entry->name = (filename3)((char *)rd_entry + sizeof(entry3));
    memcpy(rd_entry->name, entry->name, name_len);
    rd_state->next_entry = (entry3 *)(rd_entry->name + name_len);

    // try to estimate if the next entry will fit, use the current name as an estimate for the file name length
    if (rd_state->mem_left < (sizeof(entry3) + name_len)) {
        // next entry is not going to fit, don't bother reading it
        return false;
    }
    rd_state->last_retval = true;
    return true;
}


static bool readdir_plus_cb_func(EStore::ListEntry *entry, void *ctx)
{
    ReaddirState *rd_state = (ReaddirState *)ctx;
    return rd_state->srv->readdir_plus_cb(entry, ctx);
}

bool NfsServer::readdir_plus_cb(EStore::ListEntry *entry, void *ctx)
{
    ReaddirState *rd_state = (ReaddirState *)ctx;
    PT_DEBUG(DATA, "add entry handle=%lx name=%s dir_mem_left=%lu mem_left=%lu", entry->handle, entry->name,
           rd_state->dir_mem_left, rd_state->mem_left);
    rd_state->last_retval = false;
    // check if we have dir space left to store the name and file id (dir space only relates to directory information)
    // TODO use name len from entry
    uint64_t name_len = strnlen(entry->name, PATH_MAX) + 1;
    uint64_t required_space = name_len + sizeof(fileid3);
    if (rd_state->dir_mem_left < required_space) {
        return false;
    }
    rd_state->dir_mem_left -= required_space;

    // check if we have we have space to store the entry
    required_space = name_len + sizeof(entryplus3) + sizeof(EHandle);
    if (rd_state->mem_left < required_space) {
        return false;
    }
    rd_state->mem_left -= required_space;

    // move to the next entry
    if (rd_state->rdp_entry != nullptr) {
        rd_state->rdp_entry->nextentry = (entryplus3 *)rd_state->next_entry;
        rd_state->rdp_entry = rd_state->rdp_entry->nextentry;
    } else {
        // first entry
        rd_state->rdp_entry = (entryplus3 *)rd_state->next_entry;
    }
    // fill the entry values
    entryplus3 *rdp_entry = rd_state->rdp_entry;
    rdp_entry->nextentry = nullptr;

    rdp_entry->cookie = entry->offset;
    rdp_entry->fileid = entry->handle;

    SystemAttr attr;
    EStoreRes eres = _estore->get_attr(nullptr, nullptr, entry->handle, &attr, nullptr, nullptr);
    if (eres != EStoreRes::OK) {
        PT_WARN(DATA, "get_attr failed res=%d", eres);
        rdp_entry->name_attributes.attributes_follow = FALSE;
    } else {
        rdp_entry->name_attributes.attributes_follow = TRUE;
        sys_attr_to_nfs_attr(&attr, &rdp_entry->name_attributes.post_op_attr_u.attributes);
    }
    rdp_entry->name_handle.handle_follows = TRUE;
    rdp_entry->name_handle.post_op_fh3_u.handle.data.data_val = ((char*)rdp_entry + sizeof(entryplus3));
    ehandle_to_nfs_handle(entry->handle, &rdp_entry->name_handle.post_op_fh3_u.handle);
    
    rdp_entry->name = rdp_entry->name_handle.post_op_fh3_u.handle.data.data_val +
        rdp_entry->name_handle.post_op_fh3_u.handle.data.data_len;
    memcpy(rdp_entry->name, entry->name, name_len);
    rd_state->next_entry = (entryplus3 *)(rdp_entry->name + name_len);

    // try to estimate if the next entry will fit, use the current name as an estimate for the file name length
    if (rd_state->mem_left < (sizeof(entryplus3) + sizeof(EHandle) + name_len) ||
        rd_state->dir_mem_left < (sizeof(fileid3) + name_len)) {
        // next entry is not going to fit, don't bother reading it
        return false;
    }
    rd_state->last_retval = true;
    return true;
}

void NfsServer::readdir(RpcRequest *request, READDIR3args *args, READDIR3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->dir, &handle);
    uint64_t dir_ver = *(uint64_t*)&args->cookieverf;
    PT_DEBUG(DATA, "handle=%lx offset=0x%lx dir_ver=%lu", handle, args->cookie, dir_ver);

    res->READDIR3res_u.resok.reply.entries->fileid = EStore::INVALID_EHANDLE;
    ReaddirState rd_state = {
        .srv = this,
        .mem_left = P_MIN(args->count, RES_BUFFER_SIZE),
        .dir_mem_left = P_MIN(args->count, RES_BUFFER_SIZE),
        .next_entry = res->READDIR3res_u.resok.reply.entries,
        .rd_entry = nullptr,
        .rdp_entry = nullptr,
        .last_retval = true,
    };
    uint64_t current_dir_version = 0;
    SystemAttr post_attr;
    res->status = NFS3_OK;

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = EXEC_MODE,
    };

    EStoreRes eres = add_dot_files(handle, args->cookie, &rd_state, readdir_cb);
    if (eres == EStoreRes::OK) {
        eres = _estore->list_elements(access_check_cb, &check_ctx, handle, args->cookie, dir_ver, readdir_cb, &rd_state,
                                      nullptr, 0, &current_dir_version, &post_attr);
    }
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "list_elements handle=%lx offset=%ld failed res=%d", handle, args->cookie, eres);
        res->status = eres_to_nfs_status(eres);
        res->READDIR3res_u.resfail.dir_attributes.attributes_follow = FALSE;
        return;
    }
    if (res->READDIR3res_u.resok.reply.entries->fileid == EStore::INVALID_EHANDLE) {
        // no results to return
        res->READDIR3res_u.resok.reply.entries = nullptr;
    }
    READDIR3resok *resok = &res->READDIR3res_u.resok;
    *(uint64_t *)&resok->cookieverf = current_dir_version;
    resok->dir_attributes.attributes_follow = true;
    sys_attr_to_nfs_attr(&post_attr, &resok->dir_attributes.post_op_attr_u.attributes);
    resok->reply.eof = rd_state.last_retval;
}

void NfsServer::readdir_plus(RpcRequest *request, READDIRPLUS3args *args, READDIRPLUS3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->dir, &handle);
    uint64_t dir_ver = *(uint64_t*)&args->cookieverf;
    PT_DEBUG(DATA, "handle=%lx offset=0x%lx dir_ver=%lu", handle, args->cookie, dir_ver);

    res->READDIRPLUS3res_u.resok.reply.entries->fileid = EStore::INVALID_EHANDLE;
    ReaddirState rd_state = {
        .srv = this,
        .mem_left = P_MIN(args->maxcount, RES_BUFFER_SIZE),
        .dir_mem_left = P_MIN(args->dircount, RES_BUFFER_SIZE),
        .next_entry = res->READDIRPLUS3res_u.resok.reply.entries,
        .rd_entry = nullptr,
        .rdp_entry = nullptr,
        .last_retval = true,
    };
    uint64_t current_dir_version = 0;
    SystemAttr post_attr;
    res->status = NFS3_OK;

    AccessCheckCtx check_ctx = {
        .request = request,
        .required_mode = EXEC_MODE,
    };

    EStoreRes eres = add_dot_files(handle, args->cookie, &rd_state, readdir_plus_cb_func);
    if (eres == EStoreRes::OK) {
        eres = _estore->list_elements(access_check_cb, &check_ctx, handle, args->cookie, dir_ver, readdir_plus_cb_func,
                                      &rd_state, nullptr, 0, &current_dir_version, &post_attr);
    }
    if (eres != EStoreRes::OK) {
        PT_ERROR(DATA, "list_elements handle=%lx offset=%ld failed res=%d", handle, args->cookie, eres);
        res->status = eres_to_nfs_status(eres);
        res->READDIRPLUS3res_u.resfail.dir_attributes.attributes_follow = FALSE;
        return;
    }
    if (res->READDIRPLUS3res_u.resok.reply.entries->fileid == EStore::INVALID_EHANDLE) {
        // no results to return
        res->READDIRPLUS3res_u.resok.reply.entries = nullptr;
    }
    READDIRPLUS3resok *resok = &res->READDIRPLUS3res_u.resok;
    *(uint64_t *)&resok->cookieverf = current_dir_version;
    resok->dir_attributes.attributes_follow = true;
    sys_attr_to_nfs_attr(&post_attr, &resok->dir_attributes.post_op_attr_u.attributes);
    resok->reply.eof = rd_state.last_retval;
}

void NfsServer::fsstat(RpcRequest *request, FSSTAT3args *args, FSSTAT3res *res)
{
    EHandle handle;
    nfs_handle_to_ehandle(&args->fsroot, &handle);
    PT_DEBUG(DATA, "fsstat handle=%lx", handle);
    res->status = NFS3_OK;
    EStore::EStoreStats stats;
    SystemAttr attr;
    EStoreRes eres = _estore->get_stats(nullptr, nullptr, handle, &stats, &attr);
    if (eres != EStoreRes::OK) {
        PT_DEBUG(DATA, "get_stats handle=%lx failed res=%d", handle, eres);
        res->status = eres_to_nfs_status(eres);
        res->FSSTAT3res_u.resfail.obj_attributes.attributes_follow = FALSE;
        return;
    }
    FSSTAT3resok *resok = &res->FSSTAT3res_u.resok;
    resok->obj_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&attr, &resok->obj_attributes.post_op_attr_u.attributes);
    resok->tbytes = stats.total_bytes;
    resok->fbytes = stats.free_bytes;
    resok->abytes = stats.free_bytes;
    resok->tfiles = stats.total_elements;
    resok->ffiles = stats.free_elements;
    resok->afiles = stats.free_elements;
    resok->invarsec = 0;
}

void NfsServer::sys_attr_to_nfs_attr(EStore::SystemAttr *attr, fattr3 *nfs_attr)
{
    if (attr->element_flags & (uint64_t)ElementFlags::SYMLINK) {
        nfs_attr->type = NF3LNK;
    } else if (attr->element_flags & (uint64_t)ElementFlags::DIR) {
        nfs_attr->type = NF3DIR;
    } else {
        nfs_attr->type = NF3REG;
    }
    nfs_attr->mode = attr->mode;
    nfs_attr->nlink = attr->nlink;
    nfs_attr->uid = attr->uid;
    nfs_attr->gid = attr->gid;
    nfs_attr->size = attr->size;
    nfs_attr->used = attr->used;
    nfs_attr->rdev.specdata1 = 0;
    nfs_attr->rdev.specdata2 = 0;
    nfs_attr->fsid = EStore::ELEMENT_STORE_ID;
    nfs_attr->fileid = attr->fileid;
    nfs_attr->atime.seconds = NANO_TO_SEC(attr->atime);
    nfs_attr->mtime.seconds = NANO_TO_SEC(attr->mtime);
    nfs_attr->ctime.seconds = NANO_TO_SEC(attr->ctime);
    nfs_attr->atime.nseconds = attr->atime % SEC_TO_NANO(1);
    nfs_attr->mtime.nseconds = attr->mtime % SEC_TO_NANO(1);
    nfs_attr->ctime.nseconds = attr->ctime % SEC_TO_NANO(1);
}

EStore::EStoreRes NfsServer::get_attr_from_fh3(nfs_fh3 *fh3, fattr3 *attr)
{
    EHandle handle;
    nfs_handle_to_ehandle(fh3, &handle);
    PT_DEBUG(DATA, "get_attr handle=%lx", handle);

    SystemAttr sys_attr;
    EStoreRes res = _estore->get_attr(nullptr, nullptr, handle, &sys_attr, nullptr, nullptr);
    if (res != EStoreRes::OK) {
        return res;
    }
    sys_attr_to_nfs_attr(&sys_attr, attr);
    return EStoreRes::OK;
}

EStoreRes NfsServer::fill_post_op_attr(nfs_fh3 *fh3, post_op_attr *po_attr)
{
    po_attr->attributes_follow = TRUE;
    return get_attr_from_fh3(fh3, &po_attr->post_op_attr_u.attributes);
}

void NfsServer::fsinfo(RpcRequest *request, FSINFO3args *args, FSINFO3res *res)
{
    PT_DEBUG(DATA, "fs info request");
    res->status = NFS3_OK;
    EStoreRes eres = fill_post_op_attr(&args->fsroot, &res->FSINFO3res_u.resok.obj_attributes);
    if (eres != EStoreRes::OK) {
        res->status = eres_to_nfs_status(eres);
        res->FSINFO3res_u.resfail.obj_attributes.attributes_follow = FALSE;
        return;
    }

    FSINFO3resok *info = &res->FSINFO3res_u.resok;
    info->rtmax = _nfs_conf.max_read_size;
    info->rtpref =_nfs_conf.max_read_size;
    info->rtmult = UNIT_KiB * 4;
    info->wtmax = _nfs_conf.max_write_size;
    info->wtpref = _nfs_conf.max_write_size;;
    info->wtmult = UNIT_KiB * 4;
    info->dtpref = UNIT_KiB * 4;
    info->maxfilesize = EStore::MAX_ELEMENT_SIZE;
    info->time_delta.seconds = 1;
    info->time_delta.nseconds= 0;
    info->properties = FSF3_LINK | FSF3_SYMLINK | FSF3_HOMOGENEOUS | FSF3_CANSETTIME;
}

void NfsServer::pathconf(RpcRequest *request, PATHCONF3args *args, PATHCONF3res *res)
{
    PT_DEBUG(DATA, "path conf");
    res->status = NFS3_OK;
    EStoreRes eres = fill_post_op_attr(&args->object, &res->PATHCONF3res_u.resok.obj_attributes);
    if (eres != EStoreRes::OK) {
        res->status = eres_to_nfs_status(eres);
        res->PATHCONF3res_u.resfail.obj_attributes.attributes_follow = FALSE;
        return;
    }

    res->PATHCONF3res_u.resok.linkmax = EStore::MAX_LINKS;
    res->PATHCONF3res_u.resok.name_max = NAME_MAX;
    res->PATHCONF3res_u.resok.no_trunc = TRUE;
    res->PATHCONF3res_u.resok.chown_restricted = TRUE;
    res->PATHCONF3res_u.resok.case_insensitive = FALSE;
    res->PATHCONF3res_u.resok.case_preserving = TRUE;
}

void NfsServer::commit(RpcRequest *request, COMMIT3args *args, COMMIT3res *res)
{
    // This should never be called since we always return FILE_SYNC to write requests.
    // Yet in case the client is acting weird we'll just return NFS3_OK here
    EHandle handle;
    nfs_handle_to_ehandle(&args->file, &handle);
    PT_WARN(DATA, "commit request for handle=%lx", handle);
    res->status = NFS3_OK;
    memset(&res->COMMIT3res_u.resok.verf, 0, sizeof(res->COMMIT3res_u.resok.verf));
    res->COMMIT3res_u.resok.file_wcc.after.attributes_follow = FALSE;
    res->COMMIT3res_u.resok.file_wcc.before.attributes_follow = FALSE;
}

nfsstat3 NfsServer::eres_to_nfs_status(EStore::EStoreRes res)
{
    switch (res) {
        case EStoreRes::OK:
            return NFS3_OK;
        case EStoreRes::STOP:
            return NFS3ERR_SERVERFAULT;
        case EStoreRes::PERM_ERROR:
            return NFS3ERR_PERM;
        case EStoreRes::STALE:
            return NFS3ERR_STALE;
        case EStoreRes::NOENT:
            return NFS3ERR_NOENT;
        case EStoreRes::EXIST:
            return NFS3ERR_EXIST;
        case EStoreRes::IO_ERROR:
            return NFS3ERR_IO;
        case EStoreRes::NOT_SYNC:
            return NFS3ERR_NOT_SYNC;
        case EStoreRes::NO_MEM:
            return NFS3ERR_SERVERFAULT;
        case EStoreRes::INVAL:
            return NFS3ERR_INVAL;
        case EStoreRes::NOT_EMPTY:
            return NFS3ERR_NOTEMPTY;
        case EStoreRes::INVALID_ELEMENT_VERSION:
            return NFS3ERR_BAD_COOKIE;
        case EStoreRes::NOT_A_CONTAINER:
            return NFS3ERR_NOTDIR;
        case EStoreRes::NOT_A_DATA_ELEMENT:
            return NFS3ERR_ISDIR;
        case EStoreRes::LOCKED:
        case EStoreRes::NOT_IN_INGEST:
        case EStoreRes::REQUIRES_WRITE_LOCK:
        case EStoreRes::DATA_CORRUPTION:
            return NFS3ERR_SERVERFAULT;
    }
}

#define TRANSLATE_ATTR(ATTR, UNION, ENUM) \
    if (nfs_sattr->ATTR.set_it) {                           \
        sattr->ATTR = nfs_sattr->ATTR.UNION.ATTR;           \
        *(int*)&sattr->flags |= (int)AttrFlag::ENUM;        \
    }

void NfsServer::nfs_sattr_to_settable_attr(sattr3 *nfs_sattr, SettableAttr *sattr)
{
    sattr->flags = AttrFlag::NONE;
    TRANSLATE_ATTR(mode, set_mode3_u, MODE);
    TRANSLATE_ATTR(uid, set_uid3_u, UID);
    TRANSLATE_ATTR(gid, set_gid3_u, GID);
    TRANSLATE_ATTR(size, set_size3_u, SIZE);
    uint64_t time = 0;
    if (nfs_sattr->atime.set_it == SET_TO_CLIENT_TIME) {
        sattr->atime = SEC_TO_NANO(nfs_sattr->atime.set_atime_u.atime.seconds) +
        nfs_sattr->atime.set_atime_u.atime.nseconds;
        SET_ENUM_FLAG(sattr->flags, AttrFlag, ATIME);
    }
    if (nfs_sattr->atime.set_it == SET_TO_SERVER_TIME) {
        time = P::get_time_nano();
        sattr->atime = time;
        SET_ENUM_FLAG(sattr->flags, AttrFlag, ATIME);
    }
    if (nfs_sattr->mtime.set_it == SET_TO_CLIENT_TIME) {
        sattr->mtime = SEC_TO_NANO(nfs_sattr->mtime.set_mtime_u.mtime.seconds) +
        nfs_sattr->mtime.set_mtime_u.mtime.nseconds;
        SET_ENUM_FLAG(sattr->flags, AttrFlag, MTIME);
    }
    if (nfs_sattr->mtime.set_it == SET_TO_SERVER_TIME) {
        if (time == 0) {
            time = P::get_time_nano();
        }
        sattr->mtime = time;
        SET_ENUM_FLAG(sattr->flags, AttrFlag, MTIME);
    }
}

void NfsServer::set_owner_from_auth(SettableAttr *sattr, RpcRequest *request)
{
    if (!request->unix_auth_set) {
        return;
    }
    vauthsys_parms *auth = &request->auth_params;

    // if the uid / gid are not explicitly set use the caller
    if (!(sattr->flags & EStore::UID)) {
            sattr->uid = auth->uid;
            *(int*)&sattr->flags |= (int)EStore::UID;
    }
    if (!(sattr->flags & EStore::GID)) {
            sattr->gid = auth->gid;
            *(int*)&sattr->flags |= (int)EStore::GID;
    }
}

void NfsServer::fill_create_resok(CREATE3resok *resok, EStore::EHandle ehandle, EStore::SystemAttr eattr,
                                  EStore::SystemAttr pre_pattr, EStore::SystemAttr post_pattr)
{

    resok->obj.handle_follows = TRUE;
    ehandle_to_nfs_handle(ehandle, &resok->obj.post_op_fh3_u.handle);
    resok->obj_attributes.attributes_follow = TRUE;
    sys_attr_to_nfs_attr(&eattr, &resok->obj_attributes.post_op_attr_u.attributes);
    fill_wcc_data(&resok->dir_wcc, &pre_pattr, &post_pattr);
}

void NfsServer::sys_attr_to_wcc_attr(EStore::SystemAttr *attr, wcc_attr *wcc_attr)
{
    wcc_attr->ctime.seconds = NANO_TO_SEC(attr->ctime);
    wcc_attr->ctime.nseconds = attr->ctime % SEC_TO_NANO(1);
    wcc_attr->mtime.seconds = NANO_TO_SEC(attr->mtime);
    wcc_attr->mtime.nseconds = attr->mtime % SEC_TO_NANO(1);
    wcc_attr->size = attr->size;
}

EStore::EStoreRes NfsServer::add_dot_files(EStore::EHandle handle, uint64_t offset,
                                           ReaddirState *rd_state, ListCallback cb)
{
    EStore::ListEntry entry = {
        .handle = handle,
        .name = ".",
        .offset = 1,
        .is_common_prefix = false,
    };
    if (offset == 0) {
        cb(&entry, rd_state);
    }
    if (offset <= 1) {
        EStoreRes eres = _estore->lookup_parent(nullptr, nullptr, handle, &entry.handle, nullptr, nullptr);
        if (eres != EStoreRes::OK) {
            return eres;
        }
        entry.name = "..";
        entry.offset = 2;
        cb(&entry, rd_state);
    }
    return EStoreRes::OK;
}

void NfsServer::nfs_access_to_mode(bool is_dir, uint32 *access, uint32_t *mode)
{
    // remove access requests that don't match the element type
    if (is_dir) {
        *access &= ~ACCESS3_EXECUTE;
    } else {
        *access &= ~ACCESS3_LOOKUP;
        *access &= ~ACCESS3_DELETE;
    }

    *mode = 0;
    // deduce the required mode bits according to the nfs access request
    if (*access & ACCESS3_READ) {
        *mode |= READ_MODE;
    }
    if (*access & (ACCESS3_MODIFY | ACCESS3_EXTEND | ACCESS3_DELETE)) {
        *mode |= WRITE_MODE;
    }
    if (*access & (ACCESS3_LOOKUP | ACCESS3_EXECUTE)) {
        *mode |= EXEC_MODE;
    }
    return;
}

void NfsServer::mode_to_nfs_access(uint32_t mode, uint32_t *access)
{
    *access = 0;
    if (mode & READ_MODE) {
        *access |= ACCESS3_READ;
    }
    if (mode & WRITE_MODE) {
        *access |= ACCESS3_MODIFY | ACCESS3_EXTEND | ACCESS3_DELETE;
    }
    if (mode & EXEC_MODE) {
        *access |= ACCESS3_LOOKUP | ACCESS3_EXECUTE;
    }
}

}
