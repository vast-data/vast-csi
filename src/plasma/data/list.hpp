/* Copyright (C) Vast Data Ltd. */

/*!
 * \file list.hpp
 * \brief A single linked list.
 *
 * This list is used to store indices. Usually indices of objects allocated by a memory pool.
 * Therefore, the linked should be initialized with the size of the memory pool.
 *
 * More information is available here: https://vastdata.atlassian.net/wiki/display/DEV/Data+Structures
 *
 * Future considerations:
 * 1. Add thread safety.
 * 2. Consider adding debug checks to protect a user mixing anchors.
 */

#pragma once

#include "../utils/types.hpp"
#include "../utils/macros.hpp"
#include "../memory/alloc.hpp"
#include "iterable.hpp"

namespace P {

class List : public Iterable {
private:
    struct Node {
        Index next = INVALID_INDEX;
    };

public:

    class Pool {
    public:
        /*!
         * Initialize a list pool.
         * In order to destroy the list pool and release resources call destroy().
         *
         * \param size maximum number of nodes in the list pool.
         */
        void init(Index size)
        {
            _nodes = new Node[size];
    #ifdef DEBUG
        _pool_size = size;
    #endif
        }

    #ifdef DEBUG
        Index get_size() { return _pool_size; }
    #endif

        void destroy()
        {
            delete[] _nodes;
        }

        Node *_nodes;
    private:
    #ifdef DEBUG
        Index _pool_size;
    #endif
    };

    class Anchor {
    public:
        /*!
         * Returns whether a list with this anchor is empty.
         */
        bool is_empty()
        {
            DEBUG_ASSERT((head == ANCHOR_INIT) == (tail == ANCHOR_INIT));
            return head == ANCHOR_INIT;
        }

        // Since a list anchor is the index of the first element,
        // an empty list is simply an invalid index.
        static const Index ANCHOR_INIT = INVALID_INDEX;
        Index head = ANCHOR_INIT;
        Index tail = ANCHOR_INIT;
    };

    /*!
     * Initialize a list.
      * \param list out structure to initialize according to anchor and listpool. params are kept by reference,
     */
    void init(Anchor *anchor, Pool *list_pool);

    /*!
     * destroys a dlist structure.
     * NOTE: Assumes no other lists use this list pool!!!
     */
    void destroy();

    /*!
     * Returns whether a list is empty.
     */
    bool is_empty() { return _anchor->is_empty(); }

    /*!
     * Insert a new element after a given element.
     */
    void add_after(Index index, Index new_index);

    /*!
     * Insert a new element at the beginning of the list.
     */
    void push(Index index);

    /*!
     * Add an element to the end of the list.
     */
    void append(Index index);

    /*!
     * Remove the first element in the list and return it.
     */
    Index pop();

    Index remove_next(Index index);

    /*!
     * Get the first list element index (for traversal).
     */
    Index get_first() { return _anchor->head; }

    Index next(Index index) { return idx2node(index)->next; }

    /*!
     * True if the item in index is the last in the list (right before the anchor element)..
     */
    bool is_last(Index index) { DEBUG_ASSERT((next(index) == INVALID_INDEX) == (_anchor->tail == index)); return _anchor->tail == index; }

private:

    Anchor *_anchor;
    Pool *_list_pool;

    Node* idx2node(Index idx) { return &_list_pool->_nodes[idx]; }

    // TODO: perform boundary tests according to size upon insert/remove.
#ifdef DEBUG
    size_t pool_size;
#endif
};

class SingleList {
public:
    void init(Index size) { _list_pool.init(size); _list.init(&_anchor, &_list_pool); }
    void destroy() { _list_pool.destroy(); }

    List* list() { return &_list; }

private:
    List _list;
    List::Anchor _anchor;
    List::Pool _list_pool;

};

}
