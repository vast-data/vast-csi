/* Copyright (C) Vast Data Ltd. */

/*!
 * \file module_interface.hpp
 * \brief The interface for modules in our system.
 */

#pragma once

#include "plasma/utils/types.hpp"
#include "plasma/execution/config.hpp"

namespace P {
class Silo;
}

// new modules must be added to end since these IDs are passed over the network
enum class ModuleId : P::byte {
    P = 0,
    I,
    TEST,

    // must be last
    COUNT
};
static const uint8_t MODULES_COUNT = (uint8_t)ModuleId::COUNT;
// messaging uses only 4 bits for module id, if we need more than 16 modules the messaging code must be updated
static_assert(MODULES_COUNT <= 16, "the max number of supported modules is 16");

class ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting) = 0;
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
ModuleId get_module_id(const char *module_name);
