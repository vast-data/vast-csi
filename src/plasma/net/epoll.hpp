#/* Copyright (C) Vast Data Ltd. */
/*!
 * \file epoll.hpp
 * \brief A non thread safe wrapper c+ warpper for epoll.
 */

#pragma once

#include <sys/epoll.h>
#include <unistd.h>
#include "plasma/utils/assert.hpp"


namespace P {
namespace Net {

template <typename T>
class EPoll;

template <typename T>
class EPollEvent {
public:
    void init(T *ctx) { _event.data.ptr = ctx; }
    T* get() { return (T*)_event.data.ptr; }
    bool in_error() { return (_event.events & (EPOLLERR | EPOLLHUP | EPOLLRDHUP)) != 0; }
    bool has_input() { return (_event.events & EPOLLIN) != 0; }

private:
    friend class EPoll<T>;
    epoll_event _event;
};

template <typename T>
class EPoll {
public:
    void init();
    void destroy();

    // register socket for notifications on incomming events
    int register_socket(int fd, EPollEvent<T> *event);
    int wait(EPollEvent<T> *events, uint32_t n_events, int timeout_ms);

private:
    static const uint32_t MAX_EVENTS = 16;

    int _epoll_fd;
    struct epoll_event _events[MAX_EVENTS];
};

template <typename T>
void EPoll<T>::init()
{
    _epoll_fd = epoll_create1(0);
    ASSERT_ERRNO(_epoll_fd > 0);
}

template <typename T>
void EPoll<T>::destroy()
{
    close(_epoll_fd);
}

template <typename T>
int EPoll<T>::register_socket(int fd, EPollEvent<T> *event)
{
    event->_event.events = EPOLLIN | EPOLLRDHUP;
    int ret = epoll_ctl(_epoll_fd, EPOLL_CTL_ADD, fd, &event->_event);
    if (ret == -1) {
        P_TRACE(P::Trace::Channel::CONTROL, P::Trace::Severity::ERROR, ComponentId::PLASMA, "epoll_ctl errno=%d",
                errno);
        return -1;
    }
    return 0;
}

template <typename T>
int EPoll<T>::wait(EPollEvent<T> *events, uint32_t n_events, int timeout_ms)
{
    struct epoll_event *tmp_events = _events;
    int polled_events = epoll_wait(_epoll_fd, tmp_events, P_MIN(MAX_EVENTS, n_events), timeout_ms);
    if (polled_events < 0) {
        if (errno != EINTR) {
            P_TRACE(P::Trace::Channel::CONTROL, P::Trace::Severity::ERROR, ComponentId::PLASMA,
                    "poll failed errno=%d", errno);
            return 0;
        }
        return -1;
    }
    LOOP(polled_events, i) {
        events[i]._event = tmp_events[i];
    }
    return polled_events;
}

}
}
