/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_ilist.h
 * \brief A circular intrinsic doubly-linked list.
 *
 * This doubly-linked list works by storing the list nodes within the objects.
 */

#pragma once

#include <p.h>

typedef struct PIlistNode PIlistNode;

struct PIlistNode {
    PIlistNode *prev, *next;
};

void p_ilist_init(PIlistNode *head);
void p_ilist_append(PIlistNode *head, PIlistNode *node);
PIlistNode *p_ilist_next(PIlistNode *node);
bool p_ilist_empty(PIlistNode *head);
void p_ilist_remove(PIlistNode *node);

#define P_ILIST_ENTRY(type, member, member_ptr) ((type*) ((uintptr_t) (member_ptr) - offsetof(type, member)))
#define P_ILIST_EACH(anchor, node) for (ilist_node *node = (anchor)->next; node != (anchor); node = node->next)
