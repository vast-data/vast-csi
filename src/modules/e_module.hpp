/* Copyright (C) Vast Data Ltd. */

/*!
 * \file e_module.hpp
 * \brief The Env module.
 *
 * This module is initialized per silo (like all modules). Therefore, some plasma sub components which are global (like messaging) are initialized elsewhere (explicitly in the environment).
 */
#pragma once

#include "plasma/execution/env.hpp"
#include "module_interface.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/io/devio.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/memory/atomic_pool.hpp"
#include "e_module_agent.hpp"

namespace P {

class EModule : public ModuleInterface {
public:
    virtual void init(Silo *silo, Conf::ConfigSetting *setting);

    virtual void start();

    virtual Control::BaseAgent *get_control_agent() { return &_agent; }

    static ModuleId get_id() { return ModuleId::E; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

    static void init_io_from_settings(Conf::ConfigSetting *io_module, DevIO **devices, AtomicPool<DevIO::IO> *iopool,
                                      IOProvider *io_provider);

    IOProvider io_provider;
private:
    AtomicPool<DevIO::IO> iopool;
    DevIO *devices;
    EModuleAgent _agent;
};  // class EModule

}  // namespace P
