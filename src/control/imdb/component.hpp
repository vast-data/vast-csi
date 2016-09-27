/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief The-in memory DB component (used by the controller module).
 */
#pragma once

#include "plasma/memory/pool.hpp"
#include "plasma/data/hash.hpp"
#include "object.hpp"

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

struct TypeConfig {
    TypeId type_id;
    P::Index object_size;
    P::Index max_objects;
};

class IMDB {
public:
    void init(uint8_t type_count, const TypeConfig type_configs[type_count])
    {
        LOOP(TypeId::COUNT, i) {
            _pools[i] = nullptr;
            _hashes[i] = nullptr;
        }
        LOOP(type_count, i) {
            TypeId type_id = type_configs[i].type_id;
            ASSERT(_pools[(size_t)type_id] == nullptr, "The same type_id was passed more than once: " << (size_t)type_id);
            P::Index objects = type_configs[i].max_objects;
            _pools[(size_t)type_id] = new P::Pool;
            _pools[(size_t)type_id]->init(objects, type_configs[i].object_size);
            P::Index buckets = std::max(objects / 2, 1);
            _hashes[(size_t)type_id] = new P::Hash;
            _hashes[(size_t)type_id]->init_custom(buckets, objects, match_object, _pools[(size_t)type_id], object_hash_func);
        }
    }

    void destroy()
    {
        LOOP(TypeId::COUNT, i) {
            if (_hashes[i] != nullptr) {
                _hashes[i]->destroy();
                delete _hashes[i];
                _pools[i]->destroy();
                delete _pools[i];
            }
        }
    }

    template<class T>
    T *get(P::GUID guid)
    {
        DEBUG_ASSERT_OP(_hashes[(size_t)T::get_type_id_static()], !=, nullptr);
        P::Index index = _hashes[(size_t)T::get_type_id_static()]->get(&guid, sizeof(guid));
        if (index == P::INVALID_INDEX)
            return nullptr;
        return (T*) _pools[(size_t)T::get_type_id_static()]->index_to_address(index);
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

        object = new(_pools[(size_t)T::get_type_id_static()]->alloc_address()) T;
        if (object == nullptr)
            return nullptr;

        object->init();
        object->get_base()->set_guid(guid);

        _hashes[(size_t)T::get_type_id_static()]->set(&guid,
                                                      sizeof(P::GUID),
                                                      _pools[(size_t)T::get_type_id_static()]->address_to_index(object));
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
     * Remove an object.
     */
    void remove(ObjectBase *object)
    {
        P::GUID guid = object->get_base()->get_guid();
        bool existed = _hashes[(size_t)object->get_type_id()]->remove(&guid, sizeof(P::GUID));
        ASSERT(existed == true, "Removing an unknown object: " << guid);
        _pools[(size_t)object->get_type_id()]->free_address(object);
    }

private:
    P::Pool *_pools[(size_t)TypeId::COUNT];
    P::Hash *_hashes[(size_t)TypeId::COUNT];
};

class TreeDB {
public:
    void init(uint8_t type_count, const TypeConfig type_configs[type_count])
    {
        _imdb.init(type_count, type_configs);
    }

    void destroy()
    {
        _imdb.destroy();
    }

    template<class T>
    T *get(P::GUID guid)
    {
        return _imdb.get<T>(guid);
    }

    template<class T>
    T* get_or_create(P::GUID guid, bool *exists OUT, ObjectBase *parent)
    {
        T *result = _imdb.get_or_create<T>(guid, exists);
        if (result != nullptr && parent != nullptr && exists != nullptr && !*exists)
            parent->add_child(result);
        return result;
    }

    template<class T>
    T* create(P::GUID guid, ObjectBase *parent)
    {
        T* result = _imdb.create<T>(guid);
        if (result != nullptr && parent != nullptr)
            parent->add_child(result);
        return result;
    }

    /*!
     * Remove an object along with its children.
     */
    void remove(ObjectBase *object)
    {
        ILIST_ITER_SAFE(object->get_children(), i) {
            remove(p_container_of(i, ObjectBase, child_node));
        }
        object->get_parent()->remove_child(object);
        _imdb.remove(object);
    }

private:

    IMDB _imdb;
};

}
