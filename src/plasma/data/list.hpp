/* Copyright (C) Vast Data Ltd. */

/*!
 * \file list.hpp
 * \brief A single linked list.
 *
 * This list is used to store indices. Usually indices of objects allocated by a memory pool.
 * Therefore, the linked should be initialized with the size of the memory pool.
 *
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

namespace P {

class List  {
private:
    struct Node {
        Index next = INVALID_INDEX;
    };
public:

    class Pool {
    public:
        /*!
         * Initialize a listpool.
         * In order to destroy the listpool and release resources call destroy().
         *
         * \param size maximum number of nodes in the dlistpool.
         */
        void init(Index size)
        {
            _nodes = new Node[size];
        }

        void destroy()
        {
            delete[] _nodes;
        }

        Node *_nodes;
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
     * Initialize a dlist.
      * \param list out structure to initialize according to anchor and listpool. params are kept by reference,
     */
    void init(Anchor *anchor, Pool *list_pool);

    /*!
     * destroys a dlist structure.
     * NOTE: Assumes no other lists use this listpool!!!
     */
    void destroy();

    /*!
     * Returns whether a list is empty.
     */
    bool is_empty() { return _anchor->is_empty(); }

    /*!
     * Insert a new element at the beginning of the list.
     * The anchor is passed through a pointer because its value would be modified.
     */
    void insert(Index index);

    /*!
     * Insert a new element after a given element.
     */
    void add_after(Index index, Index new_index);

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

/*!
 * Iterate over list elements. It's forbidden to remove elements during iteration.
 * Example usage:
 *
\code{.c}
LIST_EACH(list, i) {
   printf("%d", i);
}
\endcode
 */
#define LIST_EACH(list, element) for (P::Index element = (list)->get_first(); \
                                       element != P::INVALID_INDEX;            \
                                       element = (list)->is_last(element) ? P::INVALID_INDEX : (list)->next(element))

// This allows current item to be removed from the list in the body of the iteration
#define LIST_SAFE_EACH(list, element, body)                                                         \
    for (P::Index element = (list)->get_first(); element != P::INVALID_INDEX;) {                     \
        P::Index next_element = (list)->is_last(element) ? P::INVALID_INDEX : (list)->next(element); \
        {body}                                                                                       \
        element = next_element;                                                                      \
  }

};
