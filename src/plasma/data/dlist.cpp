/* Copyright (C) Vast Data Ltd. */

//#include <p.h>
#include "dlist.hpp"

namespace P {

void DList::init(DList::Anchor *anchor, DList::Pool *list_pool)
{
    _anchor = anchor;
    _list_pool = list_pool;
}

void DList::destroy()
{
    P_ASSERT(_anchor->is_empty());
    _list_pool->destroy();
}

void DList::add_after(PIndex index, PIndex new_index)
{
    P_ASSERT(!is_empty());
    _list_pool->_nodes[new_index].prev = index;
    _list_pool->_nodes[new_index].next = _list_pool->_nodes[index].next;
    _list_pool->_nodes[_list_pool->_nodes[new_index].next].prev = new_index;
    _list_pool->_nodes[index].next = new_index;
}

void DList::add_before(PIndex index, PIndex new_index)
{
    P_ASSERT(!is_empty());
    _list_pool->_nodes[new_index].next = index;
    _list_pool->_nodes[new_index].prev = _list_pool->_nodes[index].prev;
    _list_pool->_nodes[_list_pool->_nodes[new_index].prev].next = new_index;
    _list_pool->_nodes[index].prev = new_index;

    if (_anchor->index == index) {
        _anchor->index = new_index;
    }
}

void DList::insert(PIndex index)
{
    if (_anchor->index != Anchor::ANCHOR_INIT) {
        add_before(_anchor->index, index);
    } else {
        _list_pool->_nodes[index].prev = index;
        _list_pool->_nodes[index].next = index;
        _anchor->index = index;
    }
}

void DList::remove(PIndex index)
{
    PIndex prev = _list_pool->_nodes[index].prev;
    PIndex next = _list_pool->_nodes[index].next;
    _list_pool->_nodes[prev].next = next;
    _list_pool->_nodes[next].prev = prev;

    if (index == _anchor->index)
        _anchor->index = next;
    if (index == next)
        _anchor->index = Anchor::ANCHOR_INIT;

#ifdef  DEBUG
    _list_pool->_nodes[index].prev = P_INVALID_INDEX;
    _list_pool->_nodes[index].next = P_INVALID_INDEX;
#endif
}

PIndex DList::next(PIndex index)
{
    return _list_pool->_nodes[index].next;
}

PIndex DList::prev(PIndex index)
{
    return _list_pool->_nodes[index].prev;
}

PIndex DList::pop()
{
    if (_anchor->index == Anchor::ANCHOR_INIT)
        return P_INVALID_INDEX;
    PIndex prev_head = _anchor->index;
    remove(_anchor->index);
    return prev_head;
}

void DList::append(PIndex index)
{
    if (_anchor->index == Anchor::ANCHOR_INIT)
        insert(index);
    else {
        PIndex last = _list_pool->_nodes[_anchor->index].prev;
        add_after(last, index);
    }
}

}
