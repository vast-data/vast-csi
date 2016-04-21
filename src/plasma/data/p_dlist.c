/* Copyright (C) Vast Data Ltd. */
#include <p.h>

struct PDlistNode {
    PIndex prev;
    PIndex next;
};

struct PDlist {
    struct PDlistNode *nodes;
};

PDlist *p_dlist_init(PIndex size)
{
    PDlist *list = p_safe_malloc(sizeof(PDlist));
    list->nodes = p_safe_malloc(sizeof(struct PDlistNode) * (size_t) size);
    return list;
}

void p_dlist_destroy(PDlist *list)
{
    p_free(list->nodes);
    p_free(list);
}

bool p_dlist_is_empty(PDlist *list, PDlistAnchor anchor) {
    (void) list;
    return anchor == P_DLIST_ANCHOR_INIT;
}

void p_dlist_insert(PDlist *list, PDlistAnchor *anchor, PIndex index)
{
    if (*anchor != P_DLIST_ANCHOR_INIT) {
        list->nodes[index].next = *anchor;
        list->nodes[index].prev = list->nodes[*anchor].prev;
        list->nodes[*anchor].prev = index;
        list->nodes[list->nodes[index].prev].next = index;
    } else {
        list->nodes[index].prev = index;
        list->nodes[index].next = index;
    }
    *anchor = index;
}

void p_dlist_add_after(PDlist *list, PDlistAnchor *anchor, PIndex index, PIndex new)
{
    P_ASSERT(!p_dlist_is_empty(list, *anchor));
    list->nodes[new].prev = index;
    list->nodes[new].next = list->nodes[index].next;
    list->nodes[list->nodes[new].next].prev = new;
    list->nodes[index].next = new;
}

void p_dlist_add_before(PDlist *list, PDlistAnchor *anchor, PIndex index, PIndex new)
{
    P_ASSERT(!p_dlist_is_empty(list, *anchor));
    list->nodes[new].next = index;
    list->nodes[new].prev = list->nodes[index].prev;
    list->nodes[list->nodes[new].prev].next = new;
    list->nodes[index].prev = new;
}

void p_dlist_remove(PDlist *list, PDlistAnchor *anchor, PIndex index)
{
    (void) anchor;

    PIndex prev = list->nodes[index].prev;
    PIndex next = list->nodes[index].next;
    list->nodes[prev].next = next;
    list->nodes[next].prev = prev;

    if (index == *anchor)
        *anchor = next;
    if (index == next)
        *anchor = P_DLIST_ANCHOR_INIT;
}

PIndex p_dlist_next(PDlist *list, PDlistAnchor *anchor, PIndex index)
{
    (void) anchor;

    return list->nodes[index].next;
}

PIndex p_dlist_prev(PDlist *list, PDlistAnchor *anchor, PIndex index)
{
    (void) anchor;

    return list->nodes[index].prev;
}

PIndex p_dlist_pop(PDlist *list, PDlistAnchor *anchor)
{
    if (*anchor == P_DLIST_ANCHOR_INIT)
        return P_INVALID_INDEX;
    PIndex head = *anchor;
    p_dlist_remove(list, anchor, *anchor);
    return head;
}

void p_dlist_append(PDlist *list, PDlistAnchor *anchor, PIndex index)
{
    if (*anchor == P_DLIST_ANCHOR_INIT)
        p_dlist_insert(list, anchor, index);
    else
        p_dlist_add_before(list, anchor, *anchor, index);
}

size_t p_dlist_length(PDlist *list, PDlistAnchor anchor)
{
    size_t count = 0;
    P_DLIST_EACH(list, anchor, i) {
        count++;
    }
    return count;
}
