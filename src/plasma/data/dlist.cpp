/* Copyright (C) Vast Data Ltd. */

#include "dlist.hpp"

#include "../utils/assert.hpp"

namespace P {

using std::size_t;

void DList::init(DList::Anchor *anchor, DList::Pool *list_pool)
{
    _anchor = anchor;
    _list_pool = list_pool;
}

void DList::destroy()
{
    ASSERT(_anchor->is_empty(), "Destroying a non-empty dlist");
    _list_pool->destroy();
}

void DList::add_after(Index index, Index new_index)
{
    ASSERT(!is_empty(), "Adding after a dlist item though the list is empty");
    _list_pool->_nodes[new_index].prev = index;
    _list_pool->_nodes[new_index].next = _list_pool->_nodes[index].next;
    _list_pool->_nodes[_list_pool->_nodes[new_index].next].prev = new_index;
    _list_pool->_nodes[index].next = new_index;
}

void DList::add_before(Index index, Index new_index)
{
    ASSERT(!is_empty(), "Adding before a dlist item though the list is empty");
    _list_pool->_nodes[new_index].next = index;
    _list_pool->_nodes[new_index].prev = _list_pool->_nodes[index].prev;
    _list_pool->_nodes[_list_pool->_nodes[new_index].prev].next = new_index;
    _list_pool->_nodes[index].prev = new_index;

    if (_anchor->index == index) {
        _anchor->index = new_index;
    }
}

void DList::insert(Index index)
{
    if (_anchor->index != Anchor::ANCHOR_INIT) {
        add_before(_anchor->index, index);
    } else {
        _list_pool->_nodes[index].prev = index;
        _list_pool->_nodes[index].next = index;
        _anchor->index = index;
    }
}

void DList::remove(Index index)
{
    Index prev = _list_pool->_nodes[index].prev;
    Index next = _list_pool->_nodes[index].next;
    _list_pool->_nodes[prev].next = next;
    _list_pool->_nodes[next].prev = prev;

    if (index == _anchor->index)
        _anchor->index = next;
    if (index == next)
        _anchor->index = Anchor::ANCHOR_INIT;

#ifdef  DEBUG
    _list_pool->_nodes[index].prev = INVALID_INDEX;
    _list_pool->_nodes[index].next = INVALID_INDEX;
#endif
}

Index DList::next(Index index)
{
    return _list_pool->_nodes[index].next;
}

Index DList::prev(Index index)
{
    return _list_pool->_nodes[index].prev;
}

Index DList::pop()
{
    if (_anchor->index == Anchor::ANCHOR_INIT)
        return INVALID_INDEX;
    Index prev_head = _anchor->index;
    remove(_anchor->index);
    return prev_head;
}

void DList::append(Index index)
{
    if (_anchor->index == Anchor::ANCHOR_INIT)
        insert(index);
    else {
        Index last = _list_pool->_nodes[_anchor->index].prev;
        add_after(last, index);
    }
}

}
