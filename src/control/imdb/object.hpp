/* Copyright (C) Vast Data Ltd. */

/*!
 * \file object.hpp
 * \brief Base system object. Used by the system state.
 */
#pragma once

#include "object.vproto.hpp"
#include "plasma/data/ilist.hpp"
#include "plasma/utils/types.hpp"

#define IMDB_ITER_CHILDREN(parent, var, child_type, body)               \
    ILIST_ITER_SAFE(parent->get_children(), i_) {                       \
        ObjectBase *child_ = p_container_of(i_, ObjectBase, child_node);\
        child_type *var;                                                \
        switch (child_->get_type_id()) {                                \
        case TypeId::child_type:                                        \
            var = child_->cast<child_type>();                           \
            { body }                                                    \
            break;                                                      \
        default:                                                        \
            break;                                                      \
        }                                                               \
    }

namespace Control {

// this enum should be coordinated with the TYPE_CONFIGS array in defs.hpp.
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
    COUNT
};

class ObjectBase {
public:
    void init()
    {
        _parent = nullptr;
        _children.init();
        child_node.init();
    }

    virtual ObjectBaseProto::Builder *get_base() = 0;
    virtual TypeId get_type_id() = 0;

    template <class T>
    T* cast()
    {
        ASSERT(T::get_type_id_static() == get_type_id(), "Invalid cast from base type to child.");
        return (T*) this;
    }

    template <class Child>
    void add_child(Child *child)
    {
        child->get_base()->set_parent_guid(get_base()->get_guid());
        _children.append(&child->child_node);
        child->_parent = this;
    }

    template <class Child>
    void remove_child(Child *child)
    {
        child->child_node.remove();
    }

    ObjectBase *get_parent()
    {
        return _parent;
    }

    P::IList *get_children()
    {
        return &_children;
    }

    template <class Child>
    Child *get_only_child()
    {
        Child *result = nullptr;
        ILIST_ITER(get_children(), i) {
            ObjectBase *child = p_container_of(i, ObjectBase, child_node);
            if (child->get_type_id() == Child::get_type_id_static()) {
                ASSERT(result == nullptr);
                result = child->cast<Child>();
            }
        }
        return result;
    }

    P::IList::Node child_node; // IList iteration requires this node to be public

private:
    P::IList _children;
    ObjectBase *_parent;
};

template <class Proto, TypeId type_id, class base = ObjectBase>
class Object : public base, public Proto::RootBuilder {
public:
    static TypeId get_type_id_static() { return type_id; }

    virtual TypeId get_type_id() { return type_id; }

    virtual ObjectBaseProto::Builder *get_base()
    {
        return Proto::RootBuilder::get_base_proto();
    }

    void init()
    {
        base::init();
        Proto::RootBuilder::init();
    }
};

}
