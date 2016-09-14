/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module.hpp
 * \brief Control module objects.
 */
#pragma once

#include "module.vproto.hpp"
#include "object.hpp"

namespace Control {

class BaseModuleLogic {
public:
    virtual void init(ModuleBaseProto::Builder *base_module)
    {
        _base_module = base_module;
    }

    ModuleBaseProto::Builder * get_base_module()
    {
        return _base_module;
    }

private:
    ModuleBaseProto::Builder *_base_module;
};

template <class ModuleProto, TypeId ModuleTypeId>
class BaseModuleObj : public Object<ModuleProto, ModuleTypeId>, public BaseModuleLogic {
public:
    virtual void init()
    {
        Object<ModuleProto, ModuleTypeId>::init();
        BaseModuleLogic::init(ModuleProto::RootBuilder::get_base_module_proto());
    }
};

class EModuleObj : public BaseModuleObj<EModuleProto, TypeId::EModule> {

};

class PModuleObj : public BaseModuleObj<PModuleProto, TypeId::PModule> {

};

class BModuleObj : public BaseModuleObj<BModuleProto, TypeId::BModule> {

};

class TModuleObj : public BaseModuleObj<TModuleProto, TypeId::TModule> {

};

class IModuleObj : public BaseModuleObj<IModuleProto, TypeId::IModule> {

};

class CModuleObj : public BaseModuleObj<CModuleProto, TypeId::CModule> {

};

}
