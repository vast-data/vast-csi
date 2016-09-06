/* Copyright (C) Vast Data Ltd. */

/*!
 * \file test_module.hpp
 * \brief A test module.
 */
#pragma once

#include "modules/module_interface.hpp"
#include "plasma/control/agent.hpp"
#include "plasma/execution/config.hpp"

namespace P {
    class Silo;
}

typedef void (*InitFunc)(P::Silo *, void *);
typedef void (*StartFunc)(void *);

class TestModule : public ModuleInterface {
public:
    virtual void init(P::Silo *silo, P::Conf::ConfigSetting *setting);
    virtual void start();
    virtual Control::BaseAgent* get_control_agent() { return &_agent; }
    static ModuleId get_id() { return ModuleId::TEST; }
    static const char *get_name() { return "TEST"; }

    static bool is_init();
    static bool is_started();
    static void set_init_func(InitFunc func, void *ctx);
    static void set_start_func(StartFunc func, void *ctx);
    static void run_start_func();

private:
    static bool _init;
    static bool _started;
    static InitFunc _init_func;
    static void *_init_func_ctx;
    static StartFunc _start_func;
    static void *_start_func_ctx;
    Control::BaseAgent _agent;
};
