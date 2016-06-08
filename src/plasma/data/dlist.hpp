/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_dlist.hpp
 * \brief A circular doubly-linked list.
 *
 * This doubly-linked list is used to store indices. Usually indices of objects allocated by a memory pool.
 * Therefore, the linked should be initialized with the size of the memory pool.
 *
 * The dlist object is actually called PDListPool because it's able to hold several sublists with the invariant
 * that every element can appear in a single list at a time.
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
#include "../memory/p_alloc.h"

namespace P {

class DList  {
private:
    struct Node {
        Index prev;
        Index next;
    };
public:
    // Todo: this seems redundant- we should use PPool<DList::Node> for this
    class Pool {
    public:
        /*!
         * Initialize a dlistpool.
         * In order to destroy the listpool and release resources call destroy().
         *
         * \param size maximum number of nodes in the dlistpool.
         * \return a pointer to a dlistpool.
         */
        void init(Index size)
        {
            _nodes = (Node*) p_safe_malloc(sizeof(Node) * (size_t) size);

        #ifdef DEBUG
            _pool_size = size;
            LOOP(size, i) {
                _nodes[i].prev = INVALID_INDEX;
                _nodes[i].next = INVALID_INDEX;
            }
        #endif

        }

        void destroy()
        {
            p_free(_nodes);
        }

        Node *_nodes;
    #ifdef DEBUG
        Index _pool_size;
    #endif
    };

    class Anchor {
    public:
        /*!
         * Initialize a dlist anchor.
         * \param anchor out structure for initialization initialize
         */
        void init()
        {
            index = ANCHOR_INIT;
        #ifdef DEBUG
            node = NULL;
        #endif
        }

        /*!
         * Returns whether a list with this anchor is empty.
         */
        bool is_empty()
        {
            return index == ANCHOR_INIT;
        }

        // Since a list anchor is the index of the first element,
        // an empty list is simply an invalid index.
        static const Index ANCHOR_INIT = INVALID_INDEX;
        Index index;
    #ifdef DEBUG
        Node *node;
    #endif
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

    /*!
     * Insert a new element before a given element.
     */
    void add_before(Index index, Index new_index);

    void remove(Index index);
    Index next(Index index);
    Index prev(Index index);

    /*!
     * Remove the first element in the list and return it.
     */
    Index pop();

    /*!
     * Add an element to the end of the list.
     */
    void append(Index index);

    /*!
     * Get the first list element index (for traversal).
     */
    Index get_first() { return _anchor->index; }

    /*!
     * True if the item in index is the last in the list (right before the anchor element)..
     */
    bool is_last(Index index) { return _list_pool->_nodes[index].next == _anchor->index; }

private:

    Anchor *_anchor;
    Pool *_list_pool;

    // TODO: perform boundary tests according to size upon insert/remove.
#ifdef DEBUG
    size_t pool_size;
#endif
};

/*!
 * Iterate over list elements. It's forbidden to remove elements during iteration.
 * Example usage:
 *
\code{.c}
P_DLIST_EACH(list, anchor, i) {
   printf("%d", i);
}
\endcode
 */
#define DLIST_EACH(list, element) for (P::Index element = (list)->get_first(); \
                                       element != P::INVALID_INDEX;            \
                                       element = (list)->is_last(element) ? P::INVALID_INDEX : (list)->next(element))

// This allows current item to be removed from the list in the body of the iteration
#define DLIST_SAFE_EACH(list, element, body)                                                         \
    for (P::Index element = (list)->get_first(); element != P::INVALID_INDEX;) {                     \
        P::Index next_element = (list)->is_last(element) ? P::INVALID_INDEX : (list)->next(element); \
        {body}                                                                                       \
        element = next_element;                                                                      \
  }

};
