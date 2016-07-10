/* Copyright (C) Vast Data Ltd. */

/*!
 * \file ilist.hpp
 * \brief Intrinsic doubly-linked list.
 */
#pragma once

#include "plasma/utils/assert.hpp"

namespace P {

class IList {
public:

    class Node {
    public:
        void init()
        {
            _next = this;
            _prev = this;
        }

        void destroy() {}

        void append(Node *node)
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
            _next = nullptr;
            _prev = nullptr;
        }

        Node *next()
        {
            return _next;
        }

        Node *prev()
        {
            return _prev;
        }

    private:
        Node *_next;
        Node *_prev;
    };

    void init()
    {
        _head.init();
    }

    void destroy() {}

    bool empty()
    {
        return _head.next() == &_head;
    }

    bool is_end(Node *node)
    {
        return node == &_head;
    }

    Node *get_first()
    {
        return _head.next();
    }

    Node *get_last()
    {
        return _head.prev();
    }

    void append(Node *node)
    {
        _head.prev()->append(node);
    }

private:
    Node _head;
};

}

/*!
 * Iterate over nodes of an intrinsic list from a given node.
 * Example usage:
 *
 \code{.c}
 ILIST_ITER_FROM(list, i, node)
     Person *person = p_container_of(i, Person, list_node);
 \endcode
*/
#define ILIST_ITER_FROM(list, element, from) for (P::IList::Node *element = from; !(list)->is_end(element); element = element->next())

/*!
 * Iterate over nodes of an intrinsic list.
 * Example usage:
 *
 \code{.c}
 ILIST_ITER(list, i)
     Person *person = p_container_of(i, Person, list_node);
 \endcode
*/
#define ILIST_ITER(list, element) ILIST_ITER_FROM(list, element, (list)->get_first())
