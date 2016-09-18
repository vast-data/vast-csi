/* Copyright (C) Vast Data Ltd. */

/*!
 * \file component.hpp
 * \brief The-in memory DB component (used by the controller module).
 */
#pragma once

#include "plasma/utils/math.hpp"
#include "plasma/memory/pool.hpp"
#include "plasma/data/ilist.hpp"
#include "plasma/data/hash.hpp"

namespace Control {

enum class TypeId : P::byte {
    System,
    CNode,
    EnvObj,
    EModuleObj,
    PModuleObj,
    BModuleObj,
    IModuleObj,
    TModuleObj,
    CModuleObj,
    DBox,
    DNode,
    NVRAM,
    Drive,
    RemoteDevice,
    COUNT
};

// The following class is a base class for all objects stored in IMDB
class BaseObject {
public:
    void init() {}

    virtual P::GUID get_guid() = 0;
    virtual void set_guid(P::GUID guid) = 0;
    virtual TypeId get_type_id() = 0;
    // This following is also required but doesn't compile (pure virtual can't be static)
    // static virtual TypeId get_type_id_static() = 0;
};

// the following functions are used by the hash table.
// the length of the key is ignored as it's a GUID and has a fixed size.

static size_t object_hash_func(void *key, size_t length)
{
    (void) length;
    P::GUID *guid = (P::GUID*) key;
    return guid->get_first_half();
}

static bool match_object(void *match_arg, P::Index index, void *key, size_t length)
{
    (void) length;
    P::Pool *pool = (P::Pool*)match_arg;
    BaseObject *p = (BaseObject*)pool->index_to_address(index);
    P::GUID *guid = (P::GUID*) key;
    return p->get_guid().equals(*guid);
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
            P::Index buckets = P::round_to_next_power_of_two(objects / 2);
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
        object->set_guid(guid);

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
    void remove(BaseObject *object)
    {
        P::GUID guid = object->get_guid();
        bool existed = _hashes[(size_t)object->get_type_id()]->remove(&guid, sizeof(P::GUID));
        ASSERT(existed == true, "Removing an unknown object: " << guid);
        _pools[(size_t)object->get_type_id()]->free_address(object);
    }

private:
    P::Pool *_pools[(size_t)TypeId::COUNT];
    P::Hash *_hashes[(size_t)TypeId::COUNT];
};

// The following class is a base class for all objects stored in TreeDB
class BaseTreeObject : public BaseObject {
public:
    void init()
    {
        _parent = nullptr;
        _children.init();
        child_node.init();
    }

    virtual void set_parent_guid(P::GUID guid) = 0;

    template <class Child>
    void add_child(Child *child)
    {
        child->set_parent_guid(get_guid());
        _children.append(&child->child_node);
        child->_parent = this;
    }

    template <class Child>
    void remove_child(Child *child)
    {
        child->child_node.remove();
    }

    template <class Parent>
    Parent *get_parent()
    {
        return (Parent*) _parent;
    }

    P::IList *get_children()
    {
        return &_children;
    }

    template <class Child>
    Child *get_first_child()
    {
        ILIST_ITER(get_children(), i) {
            Child *var = dynamic_cast<Child*>(p_container_of(i, BaseTreeObject, child_node));
            if (var != nullptr)
                return var;
        }
        return nullptr;
    }

    template <class Sibling>
    Sibling *get_next_sibling()
    {
        ILIST_ITER_FROM(_parent->get_children(), i, &child_node) {
            Sibling *var = dynamic_cast<Sibling*>(p_container_of(i, BaseTreeObject, child_node));
            if (var != nullptr && var != this)
                return var;
        }
        return nullptr;
    }

    template <class Child>
    Child *get_only_child()
    {
        Child *result = nullptr;
        ILIST_ITER(get_children(), i) {
            Child *var = dynamic_cast<Child*>(p_container_of(i, BaseTreeObject, child_node));
            if (var != nullptr) {
                ASSERT(result == nullptr);
                result = var;
            }
        }
        return result;
    }

    template <class Child>
    size_t get_children_count()
    {
        size_t count = 0;

        ILIST_ITER(get_children(), i) {
            Child *var = dynamic_cast<Child*>(p_container_of(i, BaseTreeObject, child_node));
            if (var != nullptr) {
                count++;
            }
        }
        return count;
    }

    P::IList::Node child_node; // IList iteration requires this node to be public

private:
    P::IList _children;
    BaseTreeObject *_parent;
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
    T* get_or_create(P::GUID guid, bool *exists OUT, BaseTreeObject *parent)
    {
        T *result = _imdb.get_or_create<T>(guid, exists);
        if (result != nullptr && parent != nullptr && exists != nullptr && !*exists)
            parent->add_child(result);
        return result;
    }

    template<class T>
    T* create(P::GUID guid, BaseTreeObject *parent)
    {
        T* result = _imdb.create<T>(guid);
        if (result != nullptr && parent != nullptr)
            parent->add_child(result);
        return result;
    }

    /*!
     * Remove an object along with its children.
     */
    void remove(BaseTreeObject *object)
    {
        ILIST_ITER_SAFE(object->get_children(), i) {
            remove(p_container_of(i, BaseTreeObject, child_node));
        }
        object->get_parent<BaseTreeObject>()->remove_child(object);
        _imdb.remove(object);
    }

private:
    IMDB _imdb;
};

}

#define IMDB_ITER_CHILDREN(parent, var, child_type) for (child_type *var = parent->get_first_child<child_type>(); var != nullptr; var = var->get_next_sibling<child_type>())
