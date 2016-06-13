/* Copyright (C) Vast Data Ltd. */

/*!
 * \file atomic_pool.hpp
 * \brief Extension of pool for atomic operations
 *
 * Allows retrieval of several objects atomically in a blocking fashion.
 *
 */

#pragma once

#include <stddef.h>
#include "plasma/sync/sem.hpp"
#include "object_pool.hpp"

namespace P {

template<typename T>
class AtomicPool {
public:
    /*!
     * Initialize a AtomicPool structure.
     * When finished with the AtomicPool call destroy.
     * \param element_count is the maximum value of elements to be used concurrently.
     */
    void init(size_t element_count);

    /*!
     * Allocate multiple elements.
     */
    void alloc_multiple(T* idle_elements[] OUT, uint32_t element_count);

    /*!
     * Free multiple elements
     */
    void free_multiple(T* returned_elements[], uint32_t element_count);

    /*!
     * Allocate a single element
     */
    T *alloc();

    /*!
     * Free a single element
     */
    void free(T *element);

    /*!
     * Release AtomicPool resources.
     */
    void destroy();

private:
    Sync::Sem _idle_elements;
    ObjectPool<T> _pool;
};

template<typename T>
void AtomicPool<T>::init(size_t element_count)
{
    _pool.init(element_count);
    _idle_elements.init((uint32_t) element_count);
}

template<typename T>
void AtomicPool<T>::alloc_multiple(T* idle_elements[] OUT, uint32_t element_count)
{
    _idle_elements.dec(element_count);

    LOOP_TYPE(uint32_t, element_count, element_index) {
        idle_elements[element_index] = _pool.alloc();
        ASSERT_NOT_NULL(idle_elements[element_index]);
    }
}

template<typename T>
void AtomicPool<T>::free_multiple(T* returned_elements[], uint32_t element_count)
{
    LOOP_TYPE(uint32_t, element_count, element_index) {
        _pool.free(returned_elements[element_index]);
    }

    _idle_elements.inc(element_count);
}

template<typename T>
T *AtomicPool<T>::alloc()
{
    T* idle_element;
    alloc_multiple(&idle_element, 1);
    return idle_element;
}

template<typename T>
void AtomicPool<T>::free(T *element)
{
    free_multiple(&element, 1);
}

template<typename T>
void AtomicPool<T>::destroy()
{
    _idle_elements.destroy();
    _pool.destroy();
}

}
