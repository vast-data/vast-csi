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

        void prepend(Node *node)
        {
            _prev->append(node);
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

    bool is_last(Node *node)
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
 * See ILIST_ITER_SAFE_FROM for a deletion-safe variant.
 * Example usage:
 *
 \code{.c}
 ILIST_ITER_FROM(list, i, node)
     Person *person = p_container_of(i, Person, list_node);
 \endcode
*/
#define ILIST_ITER_FROM(list, element, from) for (P::IList::Node *element = from; !(list)->is_last(element); element = element->next())

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

/*!
 * Same as ILIST_ITER_FROM but allows deletion during iteration.
*/
#define ILIST_ITER_SAFE_FROM(list, element, from) _ILIST_ITER_SAFE_FROM(list, element, from, MACRO_CONCAT(next_, __COUNTER__))
#define _ILIST_ITER_SAFE_FROM(list, element, from, next_node) for (P::IList::Node *element = from, *next_node = from->next(); !(list)->is_last(element); element = next_node, next_node = element->next())

/*!
 * Same as ILIST_ITER but allows deletion during iteration.
 */
#define ILIST_ITER_SAFE(list, element) ILIST_ITER_SAFE_FROM(list, element, (list)->get_first())
