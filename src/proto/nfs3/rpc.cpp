#include <rpc/pmap_clnt.h>
#include <unistd.h>
#include <poll.h>
#include <proto/nfs3/rpcgen/rpc_defs.h>
#include "plasma/net/net_utils.hpp"
#include "plasma/fiber/fiber.hpp"
#include "rpcgen/nfs3.h"
#include "rpcgen/rpc_defs.h"
#include "mount_server.hpp"
#include "nfs_server.hpp"
#include "nlm_server.hpp"
#include "rpc.hpp"
#include "defs.hpp"
#include "plasma/utils/assert.hpp"

using P::Net::bind_socket;
using P::Net::unblock_socket;

#define CURRENT_COMPONENT ComponentId::NFS

namespace Nfs {

int readit(char *handle, char *buff, int len)
{
    PT_DEV(DATA, "request to read %d", len);
    Rpc::Connection *conn = ((Rpc::Connection *)handle);
    for (int i = 0; i < RECV_RETRY; ++i) {
        ssize_t res = read(conn->fd, buff, len);
        if (res == -1) {
            if (errno == EAGAIN) {
                PT_DEV(DATA, "got eagain from read (socket empty)");
                P::Fiber::yield();
                continue;
            } else {
                PT_ERROR(DATA, "read from socket failed errno=%d", errno);
                return -1;
            }
        }
        if (res == 0) {
            // socket closed
            PT_WARN(DATA, "read zero bytes (peer closed socket)");
            return -1;
        }
        // as long as we manged to read something we are good
        PT_DEV(DATA, "read %ld bytes", res);
        return (int)res;
    }
    PT_ERROR(DATA, "read attempt passed max retries, returning with error");
    return -1;
}

int writeit(char *handle, char *buff, int len)
{
    int fd = ((Rpc::Connection *)handle)->fd;
//    PT_DEBUG(DATA, "request to write %d", len);
    int written = 0;
    int retry = 0;
    for (int i = 0; i < SEND_RETRY && written < len; ++i) {
        // its seems redundant to check if the socket is writable since it is non blocking
        // however for some obscure reason when we write to a full socket it gets disconnected by the peer (SIGPIPE)
        struct pollfd pfd;
        pfd.fd = fd;
        pfd.events = POLLOUT | POLLRDHUP;
        bool can_write = ::poll(&pfd, 1, 0) > 0;
        if (can_write) {
            if (pfd.revents & POLLRDHUP) {
                PT_WARN(DATA, "socket disconnected (POLLRDHUP)");
                return -1;
            }
        }
        if (!can_write) {
            retry++;
            PT_DEV(DATA, "socket full, waiting");
            P::Fiber::yield();
            continue;
        }
        ssize_t res = write(fd, buff, len);
        if (res == -1 && errno == EAGAIN) {
            PT_DEBUG(DATA, "got eagain from write (socket full)");
            P::Fiber::yield();
            continue;
        }
        if (res == -1) {
            PT_ERROR(DATA, "write failed errno=%d", errno);
            return -1;
        }
        written += len;
    }
    if (retry > 0) {
        PT_DEBUG(DATA, "written %d bytes retry=%d", written, retry);
    } else {
        PT_DEV(DATA, "written %d bytes", written);
    }
    if (written < len) {
        PT_ERROR(DATA, "write attempt passed max retries, managed to write %d bytes", written);
    }
    return written;
}

void Rpc::init(NfsConfig *nfs_conf, EStore::EStore *estore, NlmServer *nlm_server, MountServer *mount_server, NfsServer *nfs_server, bool start_udp)
{
    _estore = estore;
    _nfs_conf = *nfs_conf;
    _n_connections = 0;

    _requests.init(_nfs_conf.requests_per_silo);
    _connections.init(_nfs_conf.connections_per_silo);
    // allocate connection resources
    LOOP(_nfs_conf.connections_per_silo, i) {
        Connection *conn = _connections.index_to_address(i);
        xdrdrec_create(&conn->xdr, XDR_BUFF_SIZE, XDR_BUFF_SIZE, (caddr_t)conn, readit, writeit);
        conn->xdr.x_public = (caddr_t)this;
        conn->fd = -1;
        conn->udp_buff = nullptr;
        conn->lock.init();
    }

    _epoll.init();

    init_protocol(ProtocolType::NLM4, NLM_PROGRAM, NLM_V4, _nfs_conf.port[ProtocolType::NLM4], nlm_server, start_udp);
    init_protocol(ProtocolType::MOUNT3, MOUNT_PROGRAM, MOUNT_V3, _nfs_conf.port[ProtocolType::MOUNT3], mount_server, start_udp);
    // no support for NFS UDP yet
    init_protocol(ProtocolType::NFS3, NFS_PROGRAM, NFS_V3, _nfs_conf.port[ProtocolType::NFS3], nfs_server, false);

    LOOP(PROTOCOL_COUNT, i) {
        if (_protocols[i].udp_conn != nullptr) {
            reg_with_epoll(_protocols[i].udp_conn);
        }
    }
}

void Rpc::destroy()
{
    LOOP(_nfs_conf.connections_per_silo, i) {
        Connection *conn = _connections.index_to_address(i);
        if (conn->fd > 0) {
            close_connection(conn);
        }
        if (conn->udp_buff) {
            free(conn->udp_buff);
        }
        XDR_DESTROY(&conn->xdr);
        conn->lock.destroy();
    }
    _epoll.destroy();
    _requests.destroy();
    _connections.destroy();
}

void Rpc::decode_msg(Connection *conn, RpcRequest *request)
{
    vcall_body *call = &request->msg.body.vrpc_msg_body_u.cbody;
    PT_DEBUG(DATA, "call for prog=%u ver=%u proc=%u auth=%d", call->prog, call->vers, call->proc, call->cred.flavor);
    request->status = RpcStatus::PROG_NOT_FOUND;
    LOOP(PROTOCOL_COUNT, i) {
        Protocol *proto = &_protocols[i];
        if (proto->program == call->prog) {
            if (proto->version != call->vers) {
                request->status = RpcStatus::VER_NOT_SUPPORTED;
                return;
            }
            proto->server->set_xdr_procs(request);
            if (!request->args_proc) {
                request->status = RpcStatus::PROC_NOT_FOUND;
                return;
            }
            // decode request
            request->status = RpcStatus::OK;
            bool_t xdr_res = request->args_proc(&conn->xdr, &request->args);
            if (xdr_res == FALSE) {
                // can't decode the message, drop it
                PT_ERROR(DATA, "decode failed");
                request->status = RpcStatus::DECODE_ERROR;
                return;
            }
            return;
        }
    }
}

void Rpc::execute_request(RpcRequest *request)
{
    vcall_body *call = &request->msg.body.vrpc_msg_body_u.cbody;
    LOOP(PROTOCOL_COUNT, i) {
        Protocol *proto = &_protocols[i];
        if (proto->program == call->prog) {
            proto->server->run_procedure(request);
            return;
        }
    }
}

void Rpc::decode_header(Rpc::Connection *conn, RpcRequest *request)
{
    XDR *xdr = &conn->xdr;

    if (conn->type == ConnectionType::TCP_CONN) {
        xdr->x_op = XDR_DECODE;
        xdrdrec_skiprecord(xdr);
    } else {
        // udp
        request->addr_len = sizeof(request->addr);
        ssize_t recv_bytes = recvfrom(conn->fd, conn->udp_buff, XDR_BUFF_SIZE, 0,
                               (sockaddr *)&request->addr, &request->addr_len);
        if (recv_bytes <= 0) {
            // can't read the message, drop it
            request->status = RpcStatus::DECODE_ERROR;
            return;
        }
        PT_DEV(DATA, "UDP recv %ld bytes", recv_bytes);
        xdrmem_create(xdr, (caddr_t)conn->udp_buff, recv_bytes, XDR_DECODE);
        xdr->x_public = (caddr_t)this;
    }

    // decode header
    vrpc_msg *msg = &request->msg;
    msg->body.vrpc_msg_body_u.cbody.cred.body.body_val = request->auth_cred_buffer;
    msg->body.vrpc_msg_body_u.cbody.verf.body.body_val = request->auth_verf_buffer;
    bool_t xdr_res = xdr_vrpc_msg(xdr, msg);
    if (xdr_res == FALSE) {
        // can't read the message, drop it
        request->status = RpcStatus::DECODE_ERROR;
        PT_ERROR(DATA, "failed decoding header");
        return;
    }

    // decode auth
    request->unix_auth_set = false;
    vopaque_auth *auth = &msg->body.vrpc_msg_body_u.cbody.cred;
    if (auth->flavor == AUTH_UNIX) {
        // set internal pointers in order to avoid malloc
        request->auth_params.machinename = request->machine_name;
        request->auth_params.gids.gids_val = request->gids;
        XDR auth_xdr;
        xdrmem_create(&auth_xdr, (caddr_t)auth->body.body_val, auth->body.body_len, XDR_DECODE);
        xdr_res = xdr_vauthsys_parms(&auth_xdr, &request->auth_params);
        if (xdr_res == FALSE) {
            PT_ERROR(DATA, "failed decoding auth");
            request->status = RpcStatus::DECODE_ERROR;
            return;
        }
        request->unix_auth_set = true;
        PT_DEBUG(DATA, "auth unix: machine_name=%s uid=%d gid=%d", request->auth_params.machinename,
                 request->auth_params.uid, request->auth_params.gid);
    } else if (auth->flavor != AUTH_NONE) {
        // not supported
        PT_WARN(DATA, "unsupported auth=%d", auth->flavor);
        request->status = RpcStatus::AUTH_FAILURE;
        return;
    }
    // TODO need to verify that user / host are allowed to access the export
    // TODO id mapping
    // TODO perform root squashing if defined in the export configuration
}

static vaccept_stat request_status_to_accept_status(RpcStatus status)
{
    switch (status) {
        case RpcStatus::OK:                  return VSUCCESS;
        case RpcStatus::AUTH_FAILURE:        return VSYSTEM_ERR;
        case RpcStatus::DECODE_ERROR:        return VGARBAGE_ARGS;
        case RpcStatus::PROG_NOT_FOUND:      return VPROG_UNAVAIL;
        case RpcStatus::VER_NOT_SUPPORTED:   return VPROG_MISMATCH;
        case RpcStatus::PROC_NOT_FOUND:      return VPROC_UNAVAIL;
    }
}

void Rpc::fill_msg_header(Rpc::Connection *conn, RpcRequest *request)
{
    vrpc_msg *msg = &request->msg;
    msg->body.vrpc_msg_body_u.rbody.vreply_body_u.areply.verf.body.body_val = request->auth_verf_buffer;
    msg->body.mtype = VREPLY;
    vreply_body *reply = &msg->body.vrpc_msg_body_u.rbody;
    reply->stat = VMSG_ACCEPTED;
    reply->vreply_body_u.areply.verf.flavor = VAUTH_NONE;
    reply->vreply_body_u.areply.verf.body.body_len = 0;
    if (request->status == RpcStatus::OK) {
        reply->vreply_body_u.areply.reply_data.stat = VSUCCESS;
    } else if (request->status == RpcStatus::AUTH_FAILURE) {
        reply->stat = VMSG_DENIED;
        reply->vreply_body_u.rreply.stat = VAUTH_ERROR;
    } else {
        reply->vreply_body_u.areply.reply_data.stat = request_status_to_accept_status(request->status);
        if (reply->vreply_body_u.areply.reply_data.stat == VPROG_MISMATCH) {
            vmismatch_info* versions = &reply->vreply_body_u.areply.reply_data.vreply_data_body_u.m_info;
            versions->low = ~0;
            versions->high = 0;
            LOOP(PROTOCOL_COUNT, i) {
                if (_protocols[i].program == request->msg.body.vrpc_msg_body_u.cbody.prog) {
                    versions->low = MIN(versions->low, _protocols[i].version);
                    versions->high = MAX(versions->high, _protocols[i].version);
                }
            }
        }
    }
}

void Rpc::do_encode(Rpc::Connection *conn, RpcRequest *request)
{
    XDR *xdr = &conn->xdr;
    vrpc_msg *msg = &request->msg;

    xdr->x_op = XDR_ENCODE;
    if (conn->type == ConnectionType::UDP_CONN) {
        xdrmem_create(xdr, (caddr_t)conn->udp_buff, XDR_BUFF_SIZE, XDR_ENCODE);
    }

    vreply_body *reply = &msg->body.vrpc_msg_body_u.rbody;
    // encode header
    bool_t xdr_res = xdr_vrpc_msg(xdr, msg);
    if (xdr_res != TRUE) {
        PT_ERROR(DATA, "encode header failed");
        return;
    }
    // encode response
    if (reply->stat == VMSG_ACCEPTED) {
        xdr_res = request->res_proc(xdr, &request->res);
        if (xdr_res != TRUE) {
            PT_ERROR(DATA, "encode response failed");
            return;
        }
    }

    // send response
    if (conn->type == ConnectionType::TCP_CONN) {
        xdr_res = xdrdrec_endofrecord(xdr, true);
        if (xdr_res != TRUE) {
            PT_ERROR(DATA, "xdrdrec_endofrecord failed");
            return;
        }
    } else {
        const size_t send_bytes = XDR_GETPOS(xdr);
        ssize_t ret = sendto(conn->fd, conn->udp_buff, send_bytes, 0,
                             (sockaddr *)&request->addr, request->addr_len);
        if (ret < 0) {
            PT_ERROR(DATA, "send failed errno=%d", errno);
            return;
        }
        if (ret != send_bytes) {
            // currenlty we only use UDP fo small messages (mount protocol) so we do not expect full socket issues
            // and no retry logic has been implemented
            PT_ERROR(DATA, "failed to send full UDP message requested=%lu sent=%ld", send_bytes, ret);
            return;
        }
    }
}

void Rpc::encode_msg(Rpc::Connection *conn, RpcRequest *request)
{
    fill_msg_header(conn, request);

    conn->lock.lock();
    do_encode(conn, request);
    conn->lock.unlock();

    if (request->free_proc) {
        request->free_proc(&conn->xdr, &request->args, &request->res);
    }
    _requests.free(request);
}

static void fiber_handle_msg(void *request_arg)
{
    RpcRequest *request = (RpcRequest *)request_arg;
    Rpc::Connection *conn = (Rpc::Connection *)request->conn;
    Rpc *rpc = (Rpc *)request->rpc;
    rpc->execute_request(request);
    rpc->encode_msg(conn, request);
}

void Rpc::handle_msg(Connection *conn, RpcRequest *request)
{
//    PT_DEBUG(DATA, "handling msg on conn=%p", conn);
    request->status = RpcStatus::OK;
    decode_header(conn, request);
    if (request->status != RpcStatus::OK) {
        PT_WARN(DATA, "decode failure");
        return;
    }
    decode_msg(conn, request);
    if (request->status == RpcStatus::OK) {
        request->conn = conn;
        request->rpc = this;
        P::Fiber *fiber = P::Fiber::init((P::Index)FiberGroupId::I_PROTO, fiber_handle_msg, request, false);
        for (int i = 0; fiber == nullptr && i < ALLOCATION_RETRY; ++i) {
            PT_DEBUG(DATA, "fiber not available yield and retry fiber allocation");
            P::Fiber::yield();
            fiber = P::Fiber::init((P::Index)FiberGroupId::I_PROTO, fiber_handle_msg, request, false);
        }
        if (fiber == nullptr) {
            PT_WARN(DATA, "failed to allocate fiber, running operation on the poll fiber");
            fiber_handle_msg(request);
        }
    } else {
        // nothing to execute, send the reply inline
        encode_msg(conn, request);
    }
}

void Rpc::init_protocol(ProtocolType protocol, uint64_t program, uint64_t version,
                        const uint16_t port, RpcService *server, bool start_udp)
{
    Protocol *proto = &_protocols[protocol];
    proto->program = program;
    proto->version = version;
    proto->port = port;
    proto->server = server;
    if (start_udp) {
        allocate_udp_socket(proto);
    } else {
        proto->udp_conn = nullptr;
    }
}

void Rpc::allocate_udp_socket(Protocol *proto)
{
    Connection *conn = _connections.alloc();
    proto->udp_conn = conn;
    conn->type = ConnectionType::UDP_CONN;
    conn->fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    ASSERT_ERRNO(conn->fd > 0);
    bind_socket(conn->fd, proto->port);
    conn->udp_buff = malloc(XDR_BUFF_SIZE);
    // no need for the stream based XDR object
    XDR_DESTROY(&conn->xdr);
}

int Rpc::poll()
{
    if (_n_connections == 0)
        return 0;

    int n_events = 0;

    P::Net::EPollEvent<Connection> *events = _events;
    n_events = _epoll.wait(events, MAX_EVENTS, 0);
    if (n_events < 0) {
        PT_ERROR(DATA, "epoll failed errno=%d", errno);
        return n_events;
    }
    LOOP(n_events, i) {
        Connection *conn = events[i].get();
//        PT_DEBUG(DATA, "got event=%x conn=%p", events[i].events, conn);
        if (conn->fd < 0) {
            PT_DEBUG(DATA, "connection=%p already closed", conn);
            continue;
        }
        if (events[i].in_error()) {
            // socket closed / error
            if (conn->type == ConnectionType::TCP_CONN) {
                close_connection(conn);
            }
            continue;
        }

        if (!events[i].has_input()) {
            // shouldn't get this
            PT_ERROR(DATA, "unexpected event");
            continue;
        }
        DEBUG_ASSERT(conn->type == ConnectionType::TCP_CONN || conn->type == ConnectionType::UDP_CONN);

        bool has_more_data = true;
        bool xdr_data_available = false; //
        for (uint32_t j = 0; (j < MAX_CONN_REQUESTS_PER_POLL && has_more_data) || xdr_data_available; ++j) {
            xdr_data_available = false;
            RpcRequest *request = _requests.alloc();
            while (request == nullptr) {
                PT_DEBUG(DATA, "request object not available yielding fiber");
                P::Fiber::yield();
                request = _requests.alloc();
            }
            handle_msg(conn, request);

            // check if there is still data left in the xdr buffer
            if (conn->type == ConnectionType::TCP_CONN && !xdrdrec_eof(&conn->xdr)) {
                PT_DEV(DATA, "more input available in xdr stream");
                // if there is more data in the xdr stream we must read it now since epoll will not tell us about it
                xdr_data_available = true;
                continue;
            }

            // check if there is more data to read from the socket
            struct pollfd pfd;
            pfd.fd = conn->fd;
            pfd.events = POLLIN | POLLRDHUP;
            has_more_data = ::poll(&pfd, 1, 0) > 0;
            if (has_more_data) {
                if (pfd.revents & POLLRDHUP) {
                    PT_DEBUG(DATA, "POLLRDHUP");
                    has_more_data = false;
                }
            }
        }
    }

    return n_events;
}

void Rpc::accept_connection(P::Net::SocketId id, int fd)
{
    // add the new connection to epoll
    Connection *conn = _connections.alloc();
    PT_DEBUG(DATA, "accepted new connection on rpc_server=%p descriptor=%d conn=%p", this, fd, conn);
    conn->fd = fd;
    conn->type = ConnectionType::TCP_CONN;
    reg_with_epoll(conn);
}

int64_t Rpc::query_connection(P::Net::SocketId id)
{
    using P::Net::SocketId;
    if (id == SocketId::NFS || id == SocketId::MOUNT || id == SocketId::NLM) {
        return _n_connections;
    }
    return -1;
}

void Rpc::reg_with_epoll(Connection *conn)
{
    conn->event.init(conn);
    int ret = _epoll.register_socket(conn->fd, &conn->event);
    if (ret == -1) {
        PT_ERROR(DATA, "_epoll.register_socket errno=%d", errno);
        close(conn->fd);
        _connections.free(conn);
        return;
    }
    ++_n_connections;
}

void Rpc::close_connection(Rpc::Connection *conn)
{
    PT_DEBUG(DATA, "closing connection=%p", conn);
    close(conn->fd);
    conn->fd = -1;
    _connections.free(conn);
    --_n_connections;
}

}
