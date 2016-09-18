/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module.hpp
 * \brief Control module objects.
 */
#pragma once

#include "plasma/vmsg/vmsg_defs.hpp"
#include "module.vproto.hpp"
#include "object.hpp"

namespace Control {

class BaseModuleLogic : public ObjectBase {
public:
    virtual ModuleBaseProto::Builder *get_base_module() = 0;
    virtual P::VMsg::ModuleAddress get_address() = 0;
    virtual ModuleId get_module_id() = 0;
    virtual void activate() = 0;
};

template <class ModuleProto, TypeId type_id, ModuleId module_id>
class BaseModuleObj : public Object<ModuleProto, type_id, BaseModuleLogic> {
public:
    ModuleId get_module_id()
    {
        return module_id;
    }

    ModuleBaseProto::Builder *get_base_module()
    {
        return ModuleProto::RootBuilder::get_base_module_proto();
    }

    P::VMsg::ModuleAddress get_address()
    {
        EnvObj *parent = (EnvObj*) BaseModuleLogic::get_parent();
        return {parent->get_id(), // env_id
                0, // reserved
                (P::byte) module_id,
                get_base_module()->get_silo_id()};
    }
};

class EModuleObj : public BaseModuleObj<EModuleProto, TypeId::EModuleObj, ModuleId::E> {
    void activate()
    {

    }
};

class PModuleObj : public BaseModuleObj<PModuleProto, TypeId::PModuleObj, ModuleId::P> {
    void activate()
    {

    }
};

class BModuleObj : public BaseModuleObj<BModuleProto, TypeId::BModuleObj, ModuleId::B> {
    void activate()
    {

    }
};

class IModuleObj : public BaseModuleObj<IModuleProto, TypeId::IModuleObj, ModuleId::I> {
    void activate()
    {

    }
};

class TModuleObj : public BaseModuleObj<TModuleProto, TypeId::TModuleObj, ModuleId::TEST> {
    void activate()
    {

    }
};

class CModuleObj : public BaseModuleObj<CModuleProto, TypeId::CModuleObj, ModuleId::C> {
    void activate()
    {
        PANIC("CModule should not be activated");
    }
};

}

#define IMDB_ITER_MODULES(env, var, body)                               \
    ILIST_ITER_SAFE(env->get_children(), i) {                           \
        BaseModuleLogic *var = dynamic_cast<BaseModuleLogic*>(p_container_of(i, ObjectBase, child_node)); \
        if (var != nullptr) { body }                                    \
    }
