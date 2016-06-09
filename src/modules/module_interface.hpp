/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module_interface.hpp
 * \brief The interface for modules in our system.
 */

#pragma once

#include "plasma/execution/config.hpp"

namespace P {
class Silo;
}

enum class ModuleId : int {
    P,
    I,
    TEST,
    COUNT
};

class ModuleInterface {
public:
    virtual void *init(P::Silo *silo, P::Conf::ConfigSetting *setting) = 0;
    virtual void start() = 0;
};

/*!
 * Defines the API for creating module instances
 */
class ModuleFactory {
public:
    virtual ModuleInterface *create() = 0;
    virtual const char *get_name() = 0;
    virtual ModuleId get_id() = 0;
};

void register_modules();
const char *get_module_name(ModuleId module_id);
