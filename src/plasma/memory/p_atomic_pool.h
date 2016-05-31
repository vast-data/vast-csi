/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_atomic_pool.h
 * \brief Extension of p_pool for atomic operations
 *
 * Allows retrieval of several objects atomically in a blocking fashion.
 *
 */

#pragma once

#include <p.h>

typedef struct PAtomicPool PAtomicPool;

/*!
 * Initialize a PAtomicPool structure.
 * When finished with the PAtomicPool call p_atomic_pool_destroy.
 * \param element_count is the maximum value of elements to be used concurrently.
 */
PAtomicPool *p_atomic_pool_init(PIndex element_count, size_t element_size);

/*!
 * Retrieve an identifier of the element in the pool (index)
 */
PIndex  p_atomic_pool_element_to_index(PAtomicPool *apool, void *element);

/*!
 * Get an element address from it's pool identifier (index)
 */
void *p_atomic_pool_index_to_element(PAtomicPool *atomic_pool, PIndex index);

/*!
 * Allocate multiple elements.
 */
void p_atomic_pool_alloc_multiple(PAtomicPool *apool, PIndex idle_elements[] OUT, uint32_t element_count);

/*!
 * Free multiple elements
 */
void p_atomic_pool_free_multiple(PAtomicPool *apool, PIndex returned_elements[], uint32_t element_count);

/*!
 * Allocate a single element
 */
void *p_atomic_pool_alloc(PAtomicPool *apool);

/*!
 * Free a single element
 */
void p_atomic_pool_free(PAtomicPool *apool, void *element);

/*!
 * Release PIOPool structure resources.
 */
void p_atomic_pool_destroy(PAtomicPool *atomic_pool);

