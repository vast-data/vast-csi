/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief The-in memory DB component (used by the controller module).
 */
#pragma once

#include "plasma/memory/pool.hpp"
#include "plasma/data/hash.hpp"
#include "defs.hpp"

namespace Control {

// the following functions are used by the hash table.
// the length of the key is ignored as it's a GUID and has a fixed size.

static size_t object_hash_func(void *key, size_t length)
{
    P::GUID *guid = (P::GUID*) key;
    return guid->get_first_half();
}

static bool match_object(void *match_arg, P::Index index, void *key, size_t length)
{
    P::Pool *pool = (P::Pool*)match_arg;
    ObjectBase *p = (ObjectBase*)pool->index_to_address(index);
    P::GUID *guid = (P::GUID*) key;
    return p->get_base()->get_guid().equals(*guid);
}

class IMDB {
public:
    void init()
    {
        LOOP(TypeId::COUNT, i) {
            P::Index objects = TYPE_CONFIGS[i].max_objects;
            _pools[i].init(objects, TYPE_CONFIGS[i].object_size);
            P::Index buckets = std::max(objects / 2, 1);
            _hashes[i].init_custom(buckets, objects, match_object, &_pools[i], object_hash_func);
        }
    }

    void destroy()
    {
        LOOP(TypeId::COUNT, i) {
            _hashes[i].destroy();
            _pools[i].destroy();
        }
    }

    template<class T>
    T *get(P::GUID guid)
    {
        P::Index index = _hashes[(size_t)T::get_type_id_static()].get(&guid, sizeof(guid));
        if (index == P::INVALID_INDEX)
            return nullptr;
        return (T*) _pools[(size_t)T::get_type_id_static()].index_to_address(index);
    }

    /*!
     * Allocate a new object of type T or get it if it already exists.
     *
     * \param guid An object's GUID
     * \param exists An optional pointer to bool. Indicates whether the object existed.
     * \return a pointer to an object of type T.
     */
    template<class T>
    T* get_or_create(P::GUID guid, bool *exists OUT)
    {
        T* object = get<T>(guid);

        if (object != nullptr) {
            if (exists != nullptr)
                *exists = true;
            return object;
        }
        if (exists != nullptr)
            *exists = false;

        object = (T*) _pools[(size_t)T::get_type_id_static()].alloc_address();
        if (object == nullptr)
            return nullptr;

        object->init();
        object->get_base()->set_guid(guid);

        _hashes[(size_t)T::get_type_id_static()].set(&guid,
                                                      sizeof(P::GUID),
                                                      _pools[(size_t)T::get_type_id_static()].address_to_index(object));
        return object;
    }

    template<class T>
    T* create(P::GUID guid)
    {
        bool exists;
        T* object = get_or_create<T>(guid, &exists);
        if (object == nullptr)
            return nullptr;
        DEBUG_ASSERT(exists == false, "Object already exists in the DB: " << guid);
        return object;
    }

    /*!
     * Remove an object. T can be a pointer to a ObjectBase.
     */
    template<class T>
    void remove(T *object)
    {
        P::GUID guid = object->get_base()->get_guid();
        bool existed = _hashes[(size_t)object->get_type_id()].remove(&guid, sizeof(P::GUID));
        ASSERT(existed == true, "Removing an unknown object: " << guid);
        _pools[(size_t)object->get_type_id()].free_address(object);
    }

private:
    P::Pool _pools[(size_t)TypeId::COUNT];
    P::Hash _hashes[(size_t)TypeId::COUNT];
};

}
