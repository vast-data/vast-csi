/* Copyright (C) Vast Data Ltd. */

/*!
 * \file test_module.hpp
 * \brief A test module.
 */
#pragma once

#include "modules/module_interface.hpp"
#include "plasma/execution/config.hpp"

typedef void (*TestFunc)(void *);

namespace P {
class Silo;
}

class TestModule : public ModuleInterface {
public:
    virtual void *init(P::Silo *silo, P::Conf::ConfigSetting *setting);
    virtual void start();
    static ModuleId get_id() { return ModuleId::TEST; }
    static const char *get_name() { return "TEST"; }

    static bool is_init();
    static bool is_started();
    static void set_init_func(TestFunc func, void *ctx);
    static void set_start_func(TestFunc func, void *ctx);

private:
    static bool _init;
    static bool _started;
    static TestFunc _init_func;
    static void *_init_func_ctx;
    static TestFunc _start_func;
    static void *_start_func_ctx;
};
