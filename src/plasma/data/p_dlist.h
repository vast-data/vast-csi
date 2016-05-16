/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_dlist.h
 * \brief A circular doubly-linked list.
 *
 * This doubly-linked list is used to store indices. Usually indices of objects allocated by a memory pool.
 * Therefore, the linked should be initialized with the size of the memory pool.
 *
 * Future considerations:
 * 1. Add thread safety.
 * 2. Consider adding debug checks to protect a user mixing anchors.
 */

#pragma once

#include <p.h>

typedef struct PDListPool PDListPool;

struct PDListNode {
    PIndex prev;
    PIndex next;
};

typedef struct PDListNode PDListNode;

struct PDListAnchor {
	PIndex index;
#ifdef DEBUG
	PDListNode *node;
#endif
};
typedef struct PDListAnchor PDListAnchor;

struct PDList  {
	PDListAnchor* anchor;
	PDListPool* list_pool;

	// TODO: perform boundary tests according to size upon insert/remove.
#ifdef DEBUG
	size_t pool_size;
#endif
};
typedef struct PDList PDList;

/*!
 * Initialize a dlist anchor.
  * \param anchor out structure for initialization initialize
 */
void p_dlistanchor_init(PDListAnchor* anchor OUT);

/*!
 * Initialize a dlist.
  * \param list out structure to initialize according to anchor and listpool. params are kept by reference,
 */
void p_dlist_init(PDList* list OUT, PDListAnchor* anchor IN, PDListPool* list_pool IN);

/*!
 * Initialize a dlistpool.
 * In order to destroy the listpool and release resources call p_dlistpool_destroy().
 *
 * \param size maximum number of nodes in the dlistpool.
 * \return a pointer to a dlistpool.
 */
PDListPool *p_dlistpool_init(PIndex size);

void p_dlistpool_destroy(PDListPool *list);

/*!
 * Returns whether a list with this anchor is empty.
 */
bool p_dlistanchor_is_empty(PDListAnchor *anchor);

/*!
 * Returns whether a list is empty.
 */
bool p_dlist_is_empty(PDList *list);

/*!
 * Insert a new element at the beginning of the list.
 * The anchor is passed through a pointer because its value would be modified.
 */
void p_dlist_insert(PDList *list, PIndex index);

/*!
 * Insert a new element after a given element.
 */
void p_dlist_add_after(PDList *list, PIndex index, PIndex new);

/*!
 * Insert a new element before a given element.
 */
void p_dlist_add_before(PDList *list, PIndex index, PIndex new);

void p_dlist_remove(PDList *list, PIndex index);
PIndex p_dlist_next(PDList *list, PIndex index);
PIndex p_dlist_prev(PDList *list, PIndex index);

/*!
 * Remove the first element in the list and return it.
 */
PIndex p_dlist_pop(PDList *list);

/*!
 * Add an element to the end of the list.
 */
void p_dlist_append(PDList *list, PIndex index);

/*!
 * Return the length of the list. O(n) performance.
 */
size_t p_dlist_length(PDList *list);

/*!
 * True if the item in index is the last in the list (right before the anchor element)..
 */
bool p_dlist_is_last(PDList *list, PIndex index);

/*!
 * Get the first list element index (for traversal).
 */
PIndex p_dlist_get_first(PDList *list);

/*!
 * Iterate over list elements. It's forbidden to remove elements during iteration.
 * Example usage:
 *
\code{.c}
P_DLIST_EACH(list, anchor, i) {
   printf("%d", i);
}
\endcode
 */
#define P_DLIST_EACH(list, element) for (PIndex element = p_dlist_get_first(list); \
                                         element != P_INVALID_INDEX; \
                                         element = p_dlist_is_last(list, element) ? P_INVALID_INDEX : p_dlist_next(list, element))

