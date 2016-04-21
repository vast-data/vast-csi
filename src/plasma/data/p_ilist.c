/* Copyright (C) Vast Data Ltd. */

#include <p.h>

void p_ilist_init(PIlistNode *head)
{
    head->next = head;
    head->prev = head;
}

void p_ilist_append(PIlistNode *head, PIlistNode *node) {
    head->prev->next = node;
    node->prev = head->prev;
    node->next = head;
    head->prev = node;
}

PIlistNode *p_ilist_next(PIlistNode *node) {
    return node->next;
}

bool p_ilist_empty(PIlistNode *head)
{
    return head->next == head;
}

void p_ilist_remove(PIlistNode *node) {
    P_ASSERT(!p_ilist_empty(node));
    node->prev->next = node->next;
    node->next->prev = node->prev;
}
