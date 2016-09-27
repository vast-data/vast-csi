/* Copyright (C) Vast Data Ltd. */

/*!
 * \file c_module.hpp
 * \brief The Controller module.
 *
 * Leader election should make sure a single instance of this module is be running at any given time.
 */
#pragma once

#include "c_module.hpp"
#include "plasma/execution/silo.hpp"
#include "control/agent.hpp"
#include "control/imdb/component.hpp"
#include "control/imdb/system.hpp"
#include "control/imdb/cnode.hpp"
#include "control/imdb/env.hpp"
#include "control/imdb/module.hpp"
#include "control/imdb/dbox.hpp"
#include "control/imdb/dnode.hpp"
#include "control/imdb/nvram.hpp"
#include "control/imdb/drive.hpp"
#include "control/cluster/component.hpp"

namespace Control {

class CModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);

    virtual void start();

    virtual BaseAgent *get_control_agent() { return nullptr; }

    static ModuleId get_id() { return ModuleId::C; }

    static void generate_config(P::Conf::ConfigSetting *module_config);
    static void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);

    static constexpr TypeConfig TYPE_CONFIGS[] = {{TypeId::System, sizeof(System), 1},
                                                  {TypeId::CNode, sizeof(CNode), P::MAX_CNODES_PER_SYSTEM},
                                                  {TypeId::EnvObj, sizeof(EnvObj), P::MAX_CNODES_PER_SYSTEM * P::MAX_ENVS_PER_CNODE},
                                                  {TypeId::EModuleObj, sizeof(EModuleObj), 65536},
                                                  {TypeId::PModuleObj, sizeof(PModuleObj), P::MAX_CNODES_PER_SYSTEM},
                                                  {TypeId::BModuleObj, sizeof(BModuleObj), P::MAX_DNODES_PER_SYSTEM},
                                                  {TypeId::IModuleObj, sizeof(IModuleObj), 32768},
                                                  {TypeId::TModuleObj, sizeof(TModuleObj), 16},
                                                  {TypeId::CModuleObj, sizeof(CModuleObj), 1},
                                                  {TypeId::DBox, sizeof(DBox), P::MAX_DBOXES_PER_SYSTEM},
                                                  {TypeId::DNode, sizeof(DNode), P::MAX_DNODES_PER_SYSTEM},
                                                  {TypeId::NVRAM, sizeof(NVRAM), P::MAX_DNODES_PER_SYSTEM * P::DNODE_NVRAM_COUNT},
                                                  {TypeId::Drive, sizeof(Drive), P::MAX_DBOXES_PER_SYSTEM * P::MAX_DRIVES_PER_DBOX}};

private:
    BaseAgent _agent;
    Cluster _cluster;
    TreeDB _tree;
    System *_system;
};

} // namespace Control
