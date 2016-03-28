/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_dlist.h
 * \brief A circular doubly-linked list.
 *
 * Future considerations:
 *
 * 1. Make the dlist crash safe?
 * 2. Make the dlist thread safe?
 * 3. Consider adding debug checks in case a user mixes anchors.
 */

#pragma once

#include <p.h>

typedef struct p_dlist p_dlist;
typedef p_index p_dlist_anchor;

// Since a list anchor is the index of the first element,
// an empty list is simply an invalid index.
#define P_DLIST_ANCHOR_INIT P_INVALID_INDEX

/*!
 * Initialize a dlist.
 * In order to destroy the list and release resources call p_dlist_destroy().
 *
 * \param size maximum number of nodes in the dlist.
 * \return a pointer to a dlist.
 */
p_dlist *p_dlist_init(p_index size);

void p_dlist_destroy(p_dlist *list);

bool p_dlist_is_empty(p_dlist *list, p_dlist_anchor anchor);

/*!
 * Insert a new element at the beginning of the list.
 */
void p_dlist_insert(p_dlist *list, p_dlist_anchor *anchor, p_index index);

/*!
 * Insert a new element after a given element.
 */
void p_dlist_add_after(p_dlist *list, p_dlist_anchor *anchor, p_index index, p_index new);

/*!
 * Insert a new element before a given element.
 */
void p_dlist_add_before(p_dlist *list, p_dlist_anchor *anchor, p_index index, p_index new);

void p_dlist_remove(p_dlist *list, p_dlist_anchor *anchor, p_index index);
p_index p_dlist_next(p_dlist *list, p_dlist_anchor *anchor, p_index index);
p_index p_dlist_prev(p_dlist *list, p_dlist_anchor *anchor, p_index index);

/*!
 * Iterate over list elements. Example usage:
 *
\code{.c}
p_dlist_anchor i;
P_DLIST_EACH(list, anchor, i) {
   printf("%d", i);
}
\endcode
 */
#define P_DLIST_EACH(list, anchor, element) for (element = anchor; \
                                                 element != P_INVALID_INDEX; \
                                                 element = p_dlist_next(list, &anchor, element), \
                                                     element = element != anchor ? element : P_INVALID_INDEX)
