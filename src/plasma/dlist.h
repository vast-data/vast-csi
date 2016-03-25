/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */

/*!
 * \file dlist.h
 * \brief A circular doubly-linked list.
 *
 * Future considerations:
 *
 * 1. Make the dlist crash safe?
 * 2. Consider adding debug checks in case a user mixes anchors.
 * 3. Should the anchor have its own type?
 * 4. Compare with Intrinsic list:
 *     1. Simpler API.
 *     2. Less indirections.
 *     3. Multiple nodes of different lists on same cache line.
 *     4. Limit on number of elements.
 */
#pragma once

#include <stdbool.h>
#include "defs.h"

typedef struct p_dlist p_dlist;
typedef p_index p_dlist_anchor;

// Since a list anchor is the index of the first element,
// an empty list is simply an invalid index.
#define P_DLIST_ANCHOR_INIT P_INVALID_INDEX

/*!
 * Initialize a dlist.
 * In order to destroy the list and release resources call p_dlist__destroy().
 *
 * \param size maximum number of nodes in the dlist.
 * \return a pointer to a dlist.
 */
p_dlist *p_dlist__init(p_index size);

void p_dlist__destroy(p_dlist *list);

bool p_dlist__is_empty(p_dlist *list, p_dlist_anchor anchor);

/*!
 * Insert a new element at the beginning of the list.
 */
void p_dlist__insert(p_dlist *list, p_dlist_anchor *anchor, p_index index);

/*!
 * Insert a new element after a given element.
 */
void p_dlist__add_after(p_dlist *list, p_dlist_anchor *anchor, p_index index, p_index new);

/*!
 * Insert a new element before a given element.
 */
void p_dlist__add_before(p_dlist *list, p_dlist_anchor *anchor, p_index index, p_index new);

void p_dlist__remove(p_dlist *list, p_dlist_anchor *anchor, p_index index);
p_index p_dlist__next(p_dlist *list, p_dlist_anchor *anchor, p_index index);
p_index p_dlist__prev(p_dlist *list, p_dlist_anchor *anchor, p_index index);

/*!
 * Iterate over list elements. Example usage:
 *
\code{.c}
p_dlist_anchor i;
P_DLIST__EACH(list, anchor, i) {
   printf("%d", i);
}
\endcode
 */
#define P_DLIST__EACH(list, anchor, element) for (element = anchor; \
                                                  element != P_INVALID_INDEX; \
                                                  element = p_dlist__next(list, &anchor, element), \
                                                      element = element != anchor ? element : P_INVALID_INDEX)
