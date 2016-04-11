/* Copyright (C) Vast Data Ltd. */

#include <p.h>

void p_ilist_init(p_ilist_node *head)
{
    head->next = head;
    head->prev = head;
}

void p_ilist_append(p_ilist_node *head, p_ilist_node *node) {
    head->prev->next = node;
    node->prev = head->prev;
    node->next = head;
    head->prev = node;
}

p_ilist_node *p_ilist_next(p_ilist_node *node) {
    return node->next;
}

bool p_ilist_empty(p_ilist_node *head)
{
    return head->next == head;
}

void p_ilist_remove(p_ilist_node *node) {
    P_ASSERT(!p_ilist_empty(node));
    node->prev->next = node->next;
    node->next->prev = node->prev;
}
