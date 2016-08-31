/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief An in-memory database for objects The in memory DB component (used by the state module).
 */
#pragma once

#include "plasma/memory/pool.hpp"
#include "plasma/data/hash.hpp"
#include "defs.hpp"

namespace Control {

size_t object_hash_func(void *key, size_t length)
{
    P::GUID *guid = (P::GUID*) key;
    return guid->get_first_half();
}

bool match_object(void *match_arg, P::Index index, void *key, size_t length)
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
            P::Index objects = type_configs[i].max_objects;
            _pools[i].init(objects, type_configs[i].object_size);
            P::Index buckets = objects / 2;
            _hashes[i].init_custom(buckets, objects, match_object, &_pools[i], object_hash_func);
        }
    }

    template<class T>
    T *get(P::GUID guid)
    {
        P::Index index = _hashes[(P::byte)T::get_type_id_static()].get(&guid, sizeof(guid));
        if (index == P::INVALID_INDEX)
            return nullptr;
        return (T*) _pools[(P::byte)T::get_type_id_static()].index_to_address(index);
    }

    template<class T>
    T* create(P::GUID guid)
    {
        T* object = (T*) _pools[(P::byte)T::get_type_id_static()].alloc_address();
        if (object == nullptr)
            return nullptr;

        object->init();
        object->get_base_proto()->set_guid(guid);
        DEBUG_ASSERT(get<T>(guid) == nullptr, "Object already exists in the DB: " << guid);
        _hashes[(P::byte)T::get_type_id_static()].set(&guid,
                                               sizeof(P::GUID),
                                               _pools[(P::byte)T::get_type_id_static()].address_to_index(object));
        return object;
    }

    template<class T>
    void remove(T *object)
    {
        P::GUID guid = object->get_base()->get_guid();
        bool existed = _hashes[(P::byte)T::get_type_id_static()].remove(&guid, sizeof(P::GUID));
        ASSERT(existed == true);
        _pools[(P::byte)T::get_type_id_static()].free_address(object);
    }

private:
    P::Pool _pools[(P::byte)TypeId::COUNT];
    P::Hash _hashes[(P::byte)TypeId::COUNT];
};

}
