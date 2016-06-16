/* Copyright (C) Vast Data Ltd. */
/*!
 * \file spsc_queue.hpp
 * \brief A single producer single consumer queue.
 *
 * The queue manages indexes which are expected to be aligned with an external pool.
 * The queue allows for concurrent access by a single producer and consumer at the same time.
 * Only the producer may call push, only the consumer may call pop_all / SPSC_QUEUE_ITER.
 */

#pragma once

#include "plasma/utils/assert.hpp"
#include "plasma/utils/types.hpp"

namespace P {

class SPSCQueue {
public:
    struct Node {
        Index link;
    };

    void init()
    {
        _head = INVALID_INDEX;
        _tail = INVALID_INDEX;
    }

    void destroy()
    {
        ASSERT(empty());
    }

    bool empty() {
        return _head == _tail;
    }

    /*!
     * Push node into the queue
     */
    void push(Node *node, Index node_index) {
        node->link = _tail;
        _tail = node_index;
    }

    /*!
     * pops all of the elements in the queue and returns the head/tail.
     * During push operation the elements link points backward so in order to traverse the pop'ed elements in the order
     * they were added the caller must first traverse all the way back to the value of head prior to the pop operation
     * and than traverse forward from there. Using the macro SPSC_QUEUE_ITER hides this complication and is highly
     * recommended in order to avoid bugs.
     */
    Index pop_all(Index *prev_head) {
        *prev_head = _head;
        Index tmp = _tail;
        _head = tmp;
        return tmp;
    }

private:
    Index _head;
    Index _tail;
};

}

#define INNER_SPSC_QUEUE_ITER(HEAD, TMP, PREV, Q, GET_NODE, CURR)                                        \
           P::Index PREV = P::INVALID_INDEX;                                                             \
           P::Index TMP  = P::INVALID_INDEX;                                                             \
           P::Index HEAD;                                                                                \
           P::Index CURR = Q->pop_all(&HEAD);                                                            \
           while (CURR != HEAD) {                                                                        \
                SPSCQueue::Node *node = GET_NODE(CURR);                                                  \
                TMP = node->link;                                                                        \
                node->link = PREV;                                                                       \
                PREV = CURR;                                                                             \
                CURR = TMP;                                                                              \
            }                                                                                            \
            CURR = PREV;                                                                                 \
            for ( ; CURR != P::INVALID_INDEX ; CURR = GET_NODE(CURR)->link)


/*!
 * Traverse the list by calling pop_all and fixing the link pointers. A GET_NODE function/macro must be provided in order
 * to allow translation from list index to the node object.
 * See usage example in test_spsc_queue.cpp
 */
#define SPSC_QUEUE_ITER(Q, GET_NODE, CURR)                                                               \
    INNER_SPSC_QUEUE_ITER(MACRO_CONCAT(head, __COUNTER__), MACRO_CONCAT(tmp, __COUNTER__),               \
                          MACRO_CONCAT(prev, __COUNTER__), Q, GET_NODE, CURR)
