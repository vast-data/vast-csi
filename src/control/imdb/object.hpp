/* Copyright (C) Vast Data Ltd. */

/*!
 * \file object.hpp
 * \brief Base system object. Used by the system state.
 */
#pragma once

#include "component.hpp"

namespace Control {

// control objects are stored in the TreeDB and inherit a VProto struct for persistence
template <class Proto, TypeId type_id, class base = BaseTreeObject>
class ControlObject : public base, public Proto::RootBuilder {
public:
    static TypeId get_type_id_static() { return type_id; }

    TypeId get_type_id() { return type_id; }

    P::GUID get_guid()
    {
        return Proto::RootBuilder::get_base_proto()->get_guid();
    }

    void set_guid(P::GUID guid)
    {
        Proto::RootBuilder::get_base_proto()->set_guid(guid);
    }

    void set_parent_guid(P::GUID guid)
    {
        Proto::RootBuilder::get_base_proto()->set_parent_guid(guid);
    }

    void init()
    {
        base::init();
        Proto::RootBuilder::init();
    }
};

// objects are stored in memory using IMDB
template <TypeId type_id>
class RemoteObject : public BaseObject {
public:
    void init() { BaseObject::init(); }

    static TypeId get_type_id_static() { return type_id; }

    TypeId get_type_id() { return type_id; }

    P::GUID get_guid() { return _guid; }

    void set_guid(P::GUID guid) { _guid = guid; }

private:
    P::GUID _guid;
};

}
