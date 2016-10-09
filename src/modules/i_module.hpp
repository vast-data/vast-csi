/* Copyright (C) Vast Data Ltd. */

/*!
 * \file i_module.hpp
 * \brief The interface module.
 */
#pragma once

#include "module_interface.hpp"
#include "estore/estore.hpp"
#include "control/dev_agent/dev_agent.hpp"
#include "phys/mirrored_io/mio.hpp"
#include "plasma/execution/config.hpp"
#include "proto/nfs3/nfs_proto.hpp"
#include "i_module_agent.hpp"

class IModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);
    virtual void start();
    virtual Control::BaseAgent* get_control_agent() { return &_agent; }
    static ModuleId get_id() { return ModuleId::I; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

    void activate(); // called by control after all agents are configured.
    void create_estore(); //TODO: this could be in the W-Module instead.

private:
    bool _created_estore;
    Nfs::NfsProto _nfs;
    EStore::EStore _estore;
    Control::DevAgent _dev_agent;
    MirroredIO::MIO _mio;
    IModuleAgent _agent;
};
