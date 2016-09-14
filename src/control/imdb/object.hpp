/* Copyright (C) Vast Data Ltd. */

/*!
 * \file object.hpp
 * \brief Base system object. Used by the system state.
 */
#pragma once

#include "plasma/data/ilist.hpp"
#include "plasma/utils/types.hpp"

namespace Control {

// this enum should be coordinated with the TYPE_CONFIGS array in defs.hpp.
enum class TypeId : P::byte {
    System,
    CNode,
    Env,
    EModule,
    PModule,
    Drive,
    COUNT
};

class ObjectBase {
public:
    void init(ObjectBaseProto::Builder *base, TypeId type_id)
    {
        _base = base;
        _type_id = type_id;

        _children.init();
        child_node.init();
    }

    ObjectBaseProto::Builder *get_base()
    {
        return _base;
    }

    TypeId get_type_id()
    {
        return _type_id;
    }

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
    }

    template <class Child>
    void remove_child(Child *child)
    {
        child->child_node.remove();
    }

    P::IList *get_children()
    {
        return &_children;
    }

    P::IList::Node child_node;

private:
    ObjectBaseProto::Builder *_base;
    TypeId _type_id;
    P::IList _children;
};

template <class Proto, TypeId ThisTypeId>
class Object : public ObjectBase, public Proto::RootBuilder {
public:
    static TypeId get_type_id_static() { return ThisTypeId; };

    void init()
    {
        ObjectBase::init(Proto::RootBuilder::get_base_proto(), ThisTypeId);
        Proto::RootBuilder::init();
    }
};

}
