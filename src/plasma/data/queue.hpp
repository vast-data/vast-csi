/* Copyright (C) Vast Data Ltd. */

/*!
 * \file queue.hpp
 * \brief A pre allocated FIFO queue.
 */

#pragma once

#include <stdint.h>
#include "plasma/memory/pool.hpp"
#include "list.hpp"

namespace P {

template <class T>
class Queue {
public:

    /*!
    * Initialize the queue.
    * In order to destroy the queue and release resources call destroy().
    *
    * \param n_elements the number of elements the queue is expected to hold.
    */
    void init(uint32_t n_elements);

    /*!
     * Destroy the queue and free its resources
     */
    void destroy();

    /*!
     * Allocate an object from the queue which can later be pushed into it.
     *
     * \return an object from the queue internal pool or nullptr in case no object is available
     */
    T* alloc();

    /*!
     * Push an element to the end of the queue, the element must have been previously allocated by calling alloc()
     *
     */
    void push(T *element);


    /*!
     * Pop an element from the start of the queue, the element must eventually be returned to the queue by calling free()
     */
    T *pop();

    /*!
     * Returns the given object to the queue internal pool
     */
    void free(T *element);

private:
    P::SingleList _list;
    P::Pool _pool;
};

template <typename T>
void Queue<T>::init(uint32_t n_elements)
{
    _pool.init(n_elements, sizeof(T));
    _list.init(n_elements);
}

template <class T>
void Queue<T>::destroy()
{
    _list.destroy();
    _pool.destroy();
}

template <class T>
T *Queue<T>::alloc()
{
    return (T *)_pool.alloc_address();
}

template <class T>
void Queue<T>::push(T *element)
{
    P::Index index = _pool.address_to_index(element);
    _list.list()->append(index);
}

template <class T>
T *Queue<T>::pop()
{
    P::Index index = _list.list()->pop();
    if (index == P::INVALID_INDEX) {
        return nullptr;
    }
    return (T *)_pool.index_to_address(index);
}

template <class T>
void Queue<T>::free(T *element)
{
    _pool.free_address(element);
}

}
