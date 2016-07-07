/* Copyright (C) Vast Data Ltd. */

/*!
 * \file ilist.hpp
 * \brief Intrinsic doubly-linked list.
 */
#pragma once

#include "plasma/utils/assert.hpp"

namespace P {

class IListNode {
public:
    void init()
    {
        _next = this;
        _prev = this;
    }

    void destroy() {}

    void append(IListNode *node)
    {
        node->_next = _next;
        _next->_prev = node;
        node->_prev = this;
        _next = node;
    }

    void remove()
    {
        _prev->_next = _next;
        _next->_prev = _prev;
        _next = this;
        _prev = this;
    }

    IListNode *get_next()
    {
        return _next;
    }

    IListNode *get_prev()
    {
        return _prev;
    }

private:
    IListNode *_next;
    IListNode *_prev;
};

class IList {
public:
    void init()
    {
        _head.init();
    }

    void destroy() {}

    bool empty()
    {
        return _head.get_next() == &_head;
    }

    bool is_last(IListNode *node)
    {
        return &_head == node;
    }

    IListNode *get_first()
    {
        return _head.get_next();
    }

    IListNode *get_last()
    {
        return _head.get_prev();
    }

private:
    IListNode _head;
};

}
