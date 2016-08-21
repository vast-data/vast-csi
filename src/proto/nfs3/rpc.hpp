#/* Copyright (C) Vast Data Ltd. */
/*!
 * \file rpc.hpp
 * \brief An implementation for the SUN RPC server specification as defined in https://tools.ietf.org/html/rfc5531
 *        The implementation is targeted to serve the nfs protocol servers and no attempt have been made to make it
 *        fully generic.
 */

#pragma once

#include <stdint.h>
#include <rpc/xdr.h>
#include "third_party/xdr_drec.hpp"
#include <estore/estore.hpp>
#include "plasma/fiber/sync/qlock.hpp"
#include "nfs_defs.hpp"
#include "plasma/net/tcp_acceptor.hpp"
#include "plasma/net/epoll.hpp"
#include "plasma/memory/object_pool.hpp"
#include "plasma/memory/pool.hpp"

namespace Nfs {

class MountServer;
class NfsServer;

// The rpc service interface to be implemented by the various protocols.
class RpcService {
public:
    // Sets the pointers to the xdrproc_t parameters according to the requested procedure.
    // In addition if the request arguments / result structure contain dynamic arguments it sets the pointers in
    // order to avoid dynamic memory allocation by XDR.
    virtual void set_xdr_procs(RpcRequest *request) = 0;
    // Executes the request.
    virtual void run_procedure(RpcRequest *request) = 0;
};

// Main class of the SUN RPC server.
// The server is a uses the connection manager in order to accept connections.
class Rpc : public P::Net::TcpConsumer {
public:
    enum ConnectionType {
        TCP_CONN,
        UDP_CONN
    };

    struct Connection {
        ConnectionType type;
        P::Net::EPollEvent<Connection> event;
        int fd;
        XDR xdr;
        // network buffer used only for UDP
        void *udp_buff;
        // used to coordinate writing to the socket
        P::FiberSync::Qlock lock;
    };

    // TcpConsumer API
    virtual void accept_connection(P::Net::SocketId id, int fd) override;
    virtual int64_t query_connection(P::Net::SocketId id) override;

    void init(NfsConfig *nfs_conf, EStore::EStore *estore, MountServer *mount_server, NfsServer *nfs_server, bool start_udp);
    void destroy();

    // Check for new incoming RPC requests.
    // Return value indicates the number of events (negative in case of an error).
    int poll();

    void *alloc_data_buffer() { return _estore->alloc_data_buffer(); }
    void free_data_buffer(void *data_buffer) { _estore->free_data_buffer(data_buffer); }

    void encode_msg(Rpc::Connection *conn, RpcRequest *request);
    void execute_request(RpcRequest *request);

private:
    void do_encode(Rpc::Connection *conn, RpcRequest *request);
    void fill_msg_header(Rpc::Connection *conn, RpcRequest *request);

    struct Protocol {
        Connection *udp_conn;
        uint64_t program;
        uint64_t version;
        uint16_t port;
        RpcService *server;
    };

    void init_protocol(ProtocolType protocol, uint64_t program, uint64_t version,
                       const uint16_t port, RpcService *server, bool start_udp);
    void handle_msg(Rpc::Connection *conn, RpcRequest *request);
    void decode_header(Rpc::Connection *conn, RpcRequest *request);
    void decode_msg(Connection *conn, RpcRequest *request);

    void reg_with_epoll(Connection *conn);
    void allocate_udp_socket(Protocol *proto);
    void close_connection(Connection *conn);

private:
    static const uint32_t XDR_BUFF_SIZE = 4 * UNIT_KiB;
    static const uint32_t MAX_EVENTS = 16;

    // limits the number of requests that will be dispatched for a single connection in a single poll cycle
    // used in order ensure one connection doesn't starve the other connections
    static const uint32_t MAX_CONN_REQUESTS_PER_POLL = 8;

    EStore::EStore *_estore;
    Protocol _protocols[PROTOCOL_COUNT];

    P::Net::EPoll<Connection> _epoll;
    P::Net::EPollEvent<Connection> _events[MAX_EVENTS];
    P::ObjectPool<Connection> _connections;
    P::ObjectPool<RpcRequest> _requests;
    int64_t _n_connections;
    NfsConfig _nfs_conf;
};

}

