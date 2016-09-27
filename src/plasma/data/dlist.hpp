/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dlist.hpp
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
#include "../memory/alloc.hpp"
#include "iterable.hpp"

namespace P {

class DList
// avoiding virtual functions - yet conforming to Iterable interface
#ifdef DEBUG
        : public Iterable
#endif
{
private:
    struct Node {
        Index prev;
        Index next;
    };
public:

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
            _nodes = new Node[size];

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
         * Initialize a dlist anchor.
         * \param anchor out structure for initialization initialize
         */
        void init()
        {
            index = ANCHOR_INIT;
        #ifdef DEBUG
            node = nullptr;
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
};

// Todo: this should be unified with SingleList to a single templated code
class SingleDList {
public:
    void init(Index size) { _list_pool.init(size); _anchor.init(); _list.init(&_anchor, &_list_pool); }
    void destroy() { _list.destroy(); /* _anchor.destroy(); */_list_pool.destroy(); }

    DList* list() { return &_list; }

private:
    DList _list;
    DList::Anchor _anchor;
    DList::Pool _list_pool;

};

}
