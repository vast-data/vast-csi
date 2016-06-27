/* Copyright (C) Vast Data Ltd. */

/*!
* \file object_pool.hpp
* \brief A pool of Typed objects.
*/

#pragma once

#include "plasma/utils/types.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/data/list.hpp"

namespace P {

template<typename T>
class ObjectPool {
public:

    /*!
    * Initialize an object pool.
    * In order to destroy the pool and release resources call destroy().
    *
    * \param objects the number of objects the pool is expected to hold.
    */
    void init(size_t objects);

    /*!
    * Allocate a block from the pool.
    *
    * \return the address of the free object or nullptr if no free blocks exist.
    */
    T *alloc();

    /*!
    * Return a block to the pool.
    */
    void free(T *address);

    /*!
    * Destroy a pool in order to free its resources.
    * The ObjectPool object will be released along with the underlying memory region.
    */
    void destroy();

private:
    T *_mem;

    SingleList _free_list;

    /*!
    * Translates an absolute address to a relative index.
    */
    Index address_to_index(T *address) { return (Index)(address - _mem); }
};


template<typename T>
void ObjectPool<T>::init(size_t objects)
{
    _free_list.init(objects);
    LOOP(objects, idx) {
        _free_list.list()->append(idx);
    }

    _mem = cache_aligned_new_arr<T>(objects);
}

template<typename T>
T *ObjectPool<T>::alloc()
{
    Index index = _free_list.list()->pop();
    if (index == INVALID_INDEX) {
        return nullptr;
    }

    return &_mem[index];
}

template<typename T>
void ObjectPool<T>::free(T *address)
{
    _free_list.list()->push(address_to_index(address));
}

template<typename T>
void ObjectPool<T>::destroy()
{
    _free_list.destroy(false);
    aligned_delete(_mem);
}

}
