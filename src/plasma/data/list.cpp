/* Copyright (C) Vast Data Ltd. */

#include "list.hpp"

#include "../utils/assert.hpp"

namespace P {

using std::size_t;

void List::init(List::Anchor *anchor, List::Pool *list_pool)
{
    _anchor = anchor;
    _list_pool = list_pool;
}

void List::destroy()
{
    ASSERT(_anchor->is_empty(), "Destroying a non-empty dlist");
}

void List::add_after(Index index, Index new_index)
{
    ASSERT(!is_empty(), "Adding after a list item though the list is empty");
    DEBUG_ASSERT_OP(new_index, <=, _list_pool->get_size());
    idx2node(new_index)->next = next(index);
    idx2node(index)->next = new_index;

    if (_anchor->tail == index) {
        _anchor->tail = new_index;
    }
}

void List::push(Index index)
{
    DEBUG_ASSERT_OP(index, <=, _list_pool->get_size());
    DEBUG_ASSERT(next(index) == INVALID_INDEX);
    idx2node(index)->next = _anchor->head;
    _anchor->head = index;
    if (_anchor->tail == INVALID_INDEX) {
        _anchor->tail = index;
    }
}

void List::append(Index index)
{
    DEBUG_ASSERT(next(index) == INVALID_INDEX);
    if (_anchor->head == Anchor::ANCHOR_INIT)
        push(index);
    else {
        add_after(_anchor->tail, index);
    }
}

Index List::remove_next(Index index)
{
    DEBUG_ASSERT_OP(index, <=, _list_pool->get_size());
    Index next_idx = next(index);
    if (next_idx != INVALID_INDEX) {
        idx2node(index)->next = next(next_idx);
        idx2node(next_idx)->next = INVALID_INDEX;
        if (_anchor->tail == next_idx) {
            _anchor->tail = index;
        }
    }

    return next_idx;
}

Index List::pop()
{
    Index ret = _anchor->head;
    if (_anchor->head != Anchor::ANCHOR_INIT) {
        _anchor->head = next(_anchor->head);
        idx2node(ret)->next = INVALID_INDEX;
    }

    return ret;
}

}
