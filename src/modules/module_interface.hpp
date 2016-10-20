/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module_interface.hpp
 * \brief The interface for modules in our system.
 */

#pragma once

#include "defs.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/execution/config.hpp"

namespace P {
    class Silo;

namespace VMsg {
    struct ModuleResources;
}

}

namespace Control {
    class BaseAgent;
    class BaseTreeObject;
    class TreeDB;
    class EnvObj;
}

class ModuleInterface {
public:

    // Each inheriting module should call Agent::init() on its agent.
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting) = 0;
    virtual void start() = 0;

    virtual Control::BaseAgent* get_control_agent() = 0;

protected:
    static constexpr uint32_t DEFAULT_FIBER_STACK_SIZE = 65536;
    static constexpr uint32_t DEFAULT_NUM_SEND_BUFFERS = 64;
    static constexpr uint32_t DEFAULT_NUM_RECV_BUFFERS = 64;
    static constexpr uint32_t DEFAULT_NUM_RDMA_BUFFERS = 0;
    static constexpr uint32_t DEFAULT_SIZE_RDMA_BUFFERS = 0;

    // Helper function (to be used by the various modules) for adding the relevant fiber group settings to the config.
    static void add_fiber_group_config(P::Conf::ConfigSetting *module_config, uint32_t count, const char *group_id,
                                       uint32_t stack_size = DEFAULT_FIBER_STACK_SIZE);

    static void get_default_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources);
};

/*!
 * Defines the API for creating module instances
 */
class ModuleFactory {
public:
    virtual ModuleInterface *create() = 0;
    virtual ModuleId get_id() = 0;
    virtual void generate_config(P::Conf::ConfigSetting *module_config) = 0;
    virtual void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources) = 0;

    virtual Control::BaseTreeObject *create_control_object(Control::TreeDB *imdb, Control::EnvObj *parent) = 0;
};

class ModuleRegistry {
public:
    ModuleRegistry(ModuleRegistry const&) = delete;
    void operator=(ModuleRegistry const&) = delete;

    static void init()
    {
        LOOP(ModuleId::COUNT, i)
            get_instance()->_factories[i] = nullptr;
    }

    static ModuleFactory *get(ModuleId module_id);
    static void set(ModuleFactory *factory);

private:
    ModuleRegistry() {}

    ModuleFactory *_factories[(size_t)ModuleId::COUNT];

    static ModuleRegistry *get_instance()
    {
        static ModuleRegistry instance;
        return &instance;
    }
};
