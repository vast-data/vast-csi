/* Copyright (C) Vast Data Ltd. */

/*!
 * \file atomic_pool.hpp
 * \brief Extension of p_pool for atomic operations
 *
 * Allows retrieval of several objects atomically in a blocking fashion.
 *
 */

#pragma once

#include <stddef.h>
#include "plasma/sync/p_sem_private.h"
#include "pool.hpp"

namespace P {

class AtomicPool {
public:
    /*!
     * Initialize a PAtomicPool structure.
     * When finished with the PAtomicPool call destroy.
     * \param element_count is the maximum value of elements to be used concurrently.
     */
    void init(PIndex element_count, size_t element_size);

    /*!
     * Retrieve an identifier of the element in the pool (index)
     */
    PIndex  element_to_index(void *element);

    /*!
     * Get an element address from it's pool identifier (index)
     */
    void *index_to_element(PIndex index);

    /*!
     * Allocate multiple elements.
     */
    void alloc_multiple(PIndex idle_elements[] OUT, uint32_t element_count);

    /*!
     * Free multiple elements
     */
    void free_multiple(PIndex returned_elements[], uint32_t element_count);

    /*!
     * Allocate a single element
     */
    void *alloc();

    /*!
     * Free a single element
     */
    void free(void *element);

    /*!
     * Release PIOPool structure resources.
     */
    void destroy();

private:
    PSem _idle_elements;
    Pool _pool;
};

}