/* Copyright (C) Vast Data Ltd. */

/*!
 * \file i_module.hpp
 * \brief The interface module.
 */
#pragma once

#include "estore/estore.hpp"
#include "module_interface.hpp"
#include "plasma/execution/config.hpp"
#include "proto/nfs3/nfs_proto.hpp"


class IModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);
    virtual void start();
    static ModuleId get_id() { return ModuleId::I; }
    static const char *get_name() { return "I"; }

private:
    Nfs::NfsProto _nfs;
    EStore::EStore _estore;
};
