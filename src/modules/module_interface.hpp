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
}

namespace Control {
    class BaseAgent;
    class ObjectBase;
    class IMDB;
}

class ModuleInterface {
public:
    // Each inheriting module should call Agent::init() on its agent.
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting) = 0;
    virtual void start() = 0;

    virtual Control::BaseAgent* get_control_agent() = 0;
};

/*!
 * Defines the API for creating module instances
 */
class ModuleFactory {
public:
    virtual ModuleInterface *create() = 0;
    virtual const char *get_name() = 0;
    virtual ModuleId get_id() = 0;

    virtual Control::ObjectBase *create_control_object(Control::IMDB *imdb) = 0;
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
