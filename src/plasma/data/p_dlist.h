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

typedef struct PDlist PDlist;
typedef PIndex PDlistAnchor;

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
PDlist *p_dlist_init(PIndex size);

void p_dlist_destroy(PDlist *list);

/*!
 * Returns whether a list is empty.
 */
bool p_dlist_is_empty(PDlist *list, PDlistAnchor anchor);

/*!
 * Insert a new element at the beginning of the list.
 * The anchor is passed through a pointer because its value would be modified.
 */
void p_dlist_insert(PDlist *list, PDlistAnchor *anchor, PIndex index);

/*!
 * Insert a new element after a given element.
 */
void p_dlist_add_after(PDlist *list, PDlistAnchor *anchor, PIndex index, PIndex new);

/*!
 * Insert a new element before a given element.
 */
void p_dlist_add_before(PDlist *list, PDlistAnchor *anchor, PIndex index, PIndex new);

void p_dlist_remove(PDlist *list, PDlistAnchor *anchor, PIndex index);
PIndex p_dlist_next(PDlist *list, PDlistAnchor *anchor, PIndex index);
PIndex p_dlist_prev(PDlist *list, PDlistAnchor *anchor, PIndex index);

/*
 * Remove the first element in the list and return it.
 */
PIndex p_dlist_pop(PDlist *list, PDlistAnchor *anchor);

/*
 * Add an element to the end of the list.
 */
void p_dlist_append(PDlist *list, PDlistAnchor *anchor, PIndex index);

/*
 * Return the length of the list. O(n) performance.
 */
size_t p_dlist_length(PDlist *list, PDlistAnchor anchor);

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
#define P_DLIST_EACH(list, anchor, element) for (PDlistAnchor element = anchor; \
                                                 element != P_INVALID_INDEX; \
                                                 element = p_dlist_next(list, &anchor, element), \
                                                     element = element != anchor ? element : P_INVALID_INDEX)
