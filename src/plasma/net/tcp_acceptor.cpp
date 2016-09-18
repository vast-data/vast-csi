#include "tcp_acceptor.hpp"
#include "plasma/memory/alloc.hpp"
#include "plasma/utils/units.hpp"
#include "net_utils.hpp"
#include <sys/socket.h>
#include <rpc/types.h>
#include <unistd.h>
#include <stdint.h>

#define CURRENT_COMPONENT ComponentId::PLASMA

namespace P {
namespace Net {

void TcpAcceptor::init()
{
    LOOP(SOCKET_ID_COUNT, i) {
        fill_zeroes(&_sockets[i], sizeof(Socket));
        _sockets[i].fd = -1;
        _sockets[i].id = (SocketId)i;
    }
    LOOP(MAX_CONSUMERS, i) {
        _consumers[i] = nullptr;
    }
    _n_consumers = 0;
    _epoll.init();
}

/*static*/ void *TcpAcceptor::poll_func(void *arg)
{
    TcpAcceptor *connectionsManager = (TcpAcceptor *)arg;
    connectionsManager->poll();
    return NULL;
}

void TcpAcceptor::start()
{
    _stop = false;
    int ret = pthread_create(&_poll_thread, NULL, poll_func, this);
    ASSERT_ERRNO(ret == 0);
}

void TcpAcceptor::stop()
{
    _stop = true;
    pthread_kill(_poll_thread, SIGPOLL);
    pthread_join(_poll_thread, NULL);;
}

void TcpAcceptor::destroy()
{
    LOOP(SOCKET_ID_COUNT, i) {
        if (_sockets[i].fd > 0) {
            close(_sockets[i].fd);
        }
    }
    _epoll.destroy();
}

void TcpAcceptor::listen(SocketId socket_id, uint16_t port)
{
    PT_INFO(DATA, "Starting to listen for id=%d port=%hu", socket_id, port);
    Socket *sock = &_sockets[(int)socket_id];
    ASSERT(sock->fd == -1);
    sock->fd = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    ASSERT_ERRNO(sock->fd > 0);
    bind_socket(sock->fd, port);

    int ret = ::listen(sock->fd, SOMAXCONN);
    ASSERT_ERRNO(ret == 0);
    sock->port = port;

    sock->event.init(sock);
    ret = _epoll.register_socket(sock->fd, &sock->event);
    ASSERT_ERRNO(ret == 0);
}

void TcpAcceptor::add_consumer(TcpConsumer *consumer)
{
    ASSERT(_n_consumers < MAX_CONSUMERS);
    _consumers[_n_consumers] = consumer;
    _n_consumers++;
}

static void sig_handler(UNUSED int sig)
{
    // do nothing, this is simply used to take the thread out of epoll
}

void TcpAcceptor::poll()
{
    int n_events = 0;
    signal(SIGPOLL, sig_handler);

    while (!_stop) {
        n_events = _epoll.wait(_events, MAX_EVENTS, -1);
        if (n_events < 0) {
            if (errno == EINTR)
                continue;
            PT_ERROR(DATA, "epoll failed errno=%d", errno);
            return;
        }
        LOOP(n_events, i) {
            Socket *socket = _events[i].get();
            if (_events[i].in_error()) {
                // socket closed / error
                PT_INFO(DATA, "closing socket id=%d", socket->id);
                close(socket->fd);
                socket->fd = -1;
                // make an effort to reopen the socket for listening
                PT_INFO(DATA, "attempting to reopen socket");
                listen(socket->id, socket->port);
                continue;
            }

            if (!_events[i].has_input()) {
                // shouldn't get this
                PT_INFO(DATA, "got unexpected event");
                continue;
            }
            accept_connections(socket);
        }
    }
}

void TcpAcceptor::accept_connections(Socket *listen_socket)
{
    PT_INFO(DATA, "accepting connection listen_socket=%d", listen_socket->fd);
    while (true) {
        struct sockaddr in_addr;
        socklen_t in_len = sizeof(in_addr);
        int fd = accept(listen_socket->fd, &in_addr, &in_len);
        if (fd == -1) {
            if ((errno != EAGAIN) && (errno != EWOULDBLOCK)) {
                PT_ERROR(DATA, "accept failed errno=%d", errno);
            }
            break;
        }
        unblock_socket(fd);

        // find the consumer with the minimal number of connections
        int64_t min_conn = INT64_MAX;
        int consumer_idx = -1;
        LOOP(_n_consumers, i) {
            int64_t n_conn = _consumers[i]->query_connection(listen_socket->id);
            if (n_conn >= 0 && n_conn < min_conn) {
                min_conn = n_conn;
                consumer_idx = i;
            }
        }
        ASSERT(consumer_idx >= 0);
        _consumers[consumer_idx]->accept_connection(listen_socket->id, fd);
    }
}

}
}
