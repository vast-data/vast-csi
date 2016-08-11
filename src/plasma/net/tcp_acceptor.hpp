/* Copyright (C) Vast Data Ltd. */
/*!
 * \file tcp_acceptor.hpp
 * \brief A service for accepting and dispatching TCP connections.
 *        The connections manager works by polling the set of sockets it has been requested to. Each time a new
 *        connection comes in the connection manager dispaches it to the consumer with the smallest number of connections.
 */

#pragma once

#include <pthread.h>
#include <stdint.h>
#include "epoll.hpp"

namespace P {
namespace Net {

// known socket types
enum class SocketId {
    NFS,
    MOUNT,
    NLM,

    COUNT
};
static const uint16_t SOCKET_ID_COUNT = (uint16_t)SocketId::COUNT;

struct Socket {
    SocketId id;
    int fd;
    uint16_t port;
    EPollEvent<Socket> event;
};

// Interface for objects that accept connections.
class TcpConsumer {
public:
    // tell the consumer take ownership of a new connection
    virtual void accept_connection(SocketId id, int fd) = 0;
    // query the number of currently active connections from the given type.
    // in case the consumer is not interested in the given socket id it will return -1
    virtual int64_t query_connection(SocketId id) = 0;
};

class TcpAcceptor {
public:
    void init();
    void start();
    void stop();
    void destroy();

    // start listening on a new socket (may be called only once per socket id)
    void listen(SocketId socket_id, uint16_t port);
    // add a new consumer
    void add_consumer(TcpConsumer *consumer);

private:
    static void *poll_func(void *arg);
    void poll();
    void accept_connections(Socket *listen_socket);

private:
    static const uint16_t MAX_CONSUMERS = 128;
    static const uint16_t MAX_EVENTS = 16;
    Socket _sockets[SOCKET_ID_COUNT];
    TcpConsumer *_consumers[MAX_CONSUMERS];
    uint16_t _n_consumers;
    EPoll<Socket> _epoll;
    EPollEvent<Socket> _events[MAX_EVENTS];
    bool _stop;
    pthread_t _poll_thread;
};

}
}
