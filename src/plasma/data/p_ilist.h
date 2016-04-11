/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <p.h>

typedef struct p_ilist_node p_ilist_node;

struct p_ilist_node {
    p_ilist_node *prev, *next;
};

void p_ilist_init(p_ilist_node *head);
void p_ilist_append(p_ilist_node *head, p_ilist_node *node);
p_ilist_node *p_ilist_next(p_ilist_node *node);
bool p_ilist_empty(p_ilist_node *head);
void p_ilist_remove(p_ilist_node *node);

#define ILIST_ENTRY(type, member, member_ptr) ((type*) ((uintptr_t) (member_ptr) - offsetof(type, member)))

#define ILIST_EACH(anchor, node) for (ilist_node *node = (anchor)->next; node != (anchor); node = node->next)
