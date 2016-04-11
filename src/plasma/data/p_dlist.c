/* Copyright (C) Vast Data Ltd. */
#include <p.h>

struct p_dlist_node {
    p_index prev;
    p_index next;
};

struct p_dlist {
    struct p_dlist_node *nodes;
};

p_dlist *p_dlist_init(p_index size)
{
    p_dlist *list = p_safe_malloc(sizeof(p_dlist));
    list->nodes = p_safe_malloc(sizeof(struct p_dlist_node) * (size_t) size);
    return list;
}

void p_dlist_destroy(p_dlist *list)
{
    p_free(list->nodes);
    p_free(list);
}

bool p_dlist_is_empty(p_dlist *list, p_dlist_anchor anchor) {
    (void) list;
    return anchor == P_DLIST_ANCHOR_INIT;
}

void p_dlist_insert(p_dlist *list, p_dlist_anchor *anchor, p_index index)
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

void p_dlist_add_after(p_dlist *list, p_dlist_anchor *anchor, p_index index, p_index new)
{
    P_ASSERT(!p_dlist_is_empty(list, *anchor));
    list->nodes[new].prev = index;
    list->nodes[new].next = list->nodes[index].next;
    list->nodes[list->nodes[new].next].prev = new;
    list->nodes[index].next = new;
}

void p_dlist_add_before(p_dlist *list, p_dlist_anchor *anchor, p_index index, p_index new)
{
    P_ASSERT(!p_dlist_is_empty(list, *anchor));
    list->nodes[new].next = index;
    list->nodes[new].prev = list->nodes[index].prev;
    list->nodes[list->nodes[new].prev].next = new;
    list->nodes[index].prev = new;
}

void p_dlist_remove(p_dlist *list, p_dlist_anchor *anchor, p_index index)
{
    (void) anchor;

    p_index prev = list->nodes[index].prev;
    p_index next = list->nodes[index].next;
    list->nodes[prev].next = next;
    list->nodes[next].prev = prev;

    if (index == *anchor)
        *anchor = next;
    if (index == next)
        *anchor = P_DLIST_ANCHOR_INIT;
}

p_index p_dlist_next(p_dlist *list, p_dlist_anchor *anchor, p_index index)
{
    (void) anchor;

    return list->nodes[index].next;
}

p_index p_dlist_prev(p_dlist *list, p_dlist_anchor *anchor, p_index index)
{
    (void) anchor;

    return list->nodes[index].prev;
}

p_index p_dlist_pop(p_dlist *list, p_dlist_anchor *anchor)
{
    if (*anchor == P_DLIST_ANCHOR_INIT)
        return P_INVALID_INDEX;
    p_index head = *anchor;
    p_dlist_remove(list, anchor, *anchor);
    return head;
}

void p_dlist_append(p_dlist *list, p_dlist_anchor *anchor, p_index index)
{
    if (*anchor == P_DLIST_ANCHOR_INIT)
        p_dlist_insert(list, anchor, index);
    else
        p_dlist_add_before(list, anchor, *anchor, index);
}

size_t p_dlist_length(p_dlist *list, p_dlist_anchor anchor)
{
    size_t count = 0;
    P_DLIST_EACH(list, anchor, i) {
        count++;
    }
    return count;
}
