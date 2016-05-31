/* Copyright (C) Vast Data Ltd. */
#include <p.h>

// Since a list anchor is the index of the first element,
// an empty list is simply an invalid index.
#define P_DLIST_ANCHOR_INIT P_INVALID_INDEX

struct PDListPool {
    struct PDListNode *nodes;
#ifdef DEBUG
    PIndex pool_size;
#endif
};

inline void p_dlistanchor_init(PDListAnchor *anchor OUT)
{
    anchor->index = P_DLIST_ANCHOR_INIT;
#ifdef DEBUG
    anchor->node = NULL;
#endif
}

void p_dlist_init(PDList *list OUT, PDListAnchor *anchor IN, PDListPool *list_pool IN)
{
    list->anchor = anchor;
    list->list_pool = list_pool;
}

PDListPool *p_dlistpool_init(PIndex size)
{
    PDListPool *listpool = p_safe_malloc(sizeof(PDList));
    listpool->nodes = p_safe_malloc(sizeof(struct PDListNode) * (size_t) size);

#ifdef DEBUG
    listpool->pool_size = size;
    LOOP(size, index) {
        listpool->nodes[index].prev = P_INVALID_INDEX;
        listpool->nodes[index].next = P_INVALID_INDEX;
    }
#endif
    return listpool;
}

void p_dlistpool_destroy(PDListPool *listpool)
{
    p_free(listpool->nodes);
    p_free(listpool);
}

void p_dlist_destroy(PDList *list)
{
    P_ASSERT(p_dlistanchor_is_empty(list->anchor));
    p_dlistpool_destroy(list->list_pool);
}

inline bool p_dlistanchor_is_empty(PDListAnchor *anchor)
{
    return anchor->index == P_DLIST_ANCHOR_INIT;
}

inline bool p_dlist_is_empty(PDList *list)
{
    return p_dlistanchor_is_empty(list->anchor);
}

inline bool p_dlist_is_last(PDList *list, PIndex index)
{
    return list->list_pool->nodes[index].next == list->anchor->index;
}

inline PIndex p_dlist_get_first(PDList *list)
{
    return list->anchor->index;
}

void p_dlist_add_after(PDList *list, PIndex index, PIndex new)
{
    P_ASSERT(!p_dlist_is_empty(list));
    list->list_pool->nodes[new].prev = index;
    list->list_pool->nodes[new].next = list->list_pool->nodes[index].next;
    list->list_pool->nodes[list->list_pool->nodes[new].next].prev = new;
    list->list_pool->nodes[index].next = new;
}

void p_dlist_add_before(PDList *list, PIndex index, PIndex new)
{
    P_ASSERT(!p_dlist_is_empty(list));
    list->list_pool->nodes[new].next = index;
    list->list_pool->nodes[new].prev = list->list_pool->nodes[index].prev;
    list->list_pool->nodes[list->list_pool->nodes[new].prev].next = new;
    list->list_pool->nodes[index].prev = new;

    if (list->anchor->index == index) {
        list->anchor->index = new;
    }
}

void p_dlist_insert(PDList *list, PIndex index)
{
    if (list->anchor->index != P_DLIST_ANCHOR_INIT) {
        p_dlist_add_before(list, list->anchor->index, index);
    } else {
        list->list_pool->nodes[index].prev = index;
        list->list_pool->nodes[index].next = index;
        list->anchor->index = index;
    }
}

void p_dlist_remove(PDList *list, PIndex index)
{
    PIndex prev = list->list_pool->nodes[index].prev;
    PIndex next = list->list_pool->nodes[index].next;
    list->list_pool->nodes[prev].next = next;
    list->list_pool->nodes[next].prev = prev;

    if (index == list->anchor->index)
        list->anchor->index = next;
    if (index == next)
        list->anchor->index = P_DLIST_ANCHOR_INIT;

#ifdef  DEBUG
    list->list_pool->nodes[index].prev = P_INVALID_INDEX;
    list->list_pool->nodes[index].next = P_INVALID_INDEX;
#endif
}

PIndex p_dlist_next(PDList *list, PIndex index)
{
    return list->list_pool->nodes[index].next;
}

PIndex p_dlist_prev(PDList *list, PIndex index)
{
    return list->list_pool->nodes[index].prev;
}

PIndex p_dlist_pop(PDList *list)
{
    if (list->anchor->index == P_DLIST_ANCHOR_INIT)
        return P_INVALID_INDEX;
    PIndex prev_head = list->anchor->index;
    p_dlist_remove(list, list->anchor->index);
    return prev_head;
}

void p_dlist_append(PDList *list, PIndex index)
{
    if (list->anchor->index == P_DLIST_ANCHOR_INIT)
        p_dlist_insert(list, index);
    else {
        PIndex last = list->list_pool->nodes[list->anchor->index].prev;
        p_dlist_add_after(list, last, index);
    }
}
