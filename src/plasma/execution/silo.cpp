/* Copyright (C) Vast Data Ltd. */
//#define _GNU_SOURCE

#include "silo.hpp"

#include <sched.h>
#include <limits.h>
#include <signal.h>
#include <pthread.h>
#include <stdio.h>

#include "modules/module_interface.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/utils/os.hpp"
#include "plasma/memory/alloc.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/control/agent.hpp"
#include "plasma/internal.hpp"
#include "globals.hpp"
#include "config.hpp"
#include "defs.hpp"
#include "env.hpp"

namespace P {

using namespace P::Conf;

static thread_local Silo *current_silo = nullptr;

void Silo::init(ConfigSetting *silo_config, int32_t affinity, SiloId silo_id, const char *data_dir, const char *trace_dir)
{
    _affinity = affinity;
    _silo_id = silo_id;

    _scheduler_config.group_count = (Index)FiberGroupId::COUNT;
    _scheduler_config.fiber_groups = new FiberGroupConfig[_scheduler_config.group_count](); // () assures this is zeroed

    ConfigSetting *modules_setting = conf_setting_lookup_required(silo_config, "modules");
    LOOP(conf_setting_length(modules_setting), i) {
        ConfigSetting *module_setting = conf_setting_get_element(modules_setting, (uint32_t) i);
        const char *module_name = conf_setting_name(module_setting);

        ModuleId module_id;
        ModuleInterface *module = Env::get()->create_module(module_name, &module_id);
        _module_descriptors[(int)module_id].defined = true;
        _module_descriptors[(int)module_id].module = module;
        module->init(this, module_setting);
        // Each module is responsible for calling allocating its agent and calling Agent::init() on it.
        if (module->get_control_agent() != nullptr)
            ASSERT(module->get_control_agent()->is_initialized());

        ConfigSetting *fibers_setting = conf_setting_lookup_required(module_setting, "fibers");
        LOOP(conf_setting_length(fibers_setting), j) {
            ConfigSetting *fiber_group_setting = conf_setting_get_element(fibers_setting, (uint32_t) j);
            ConfigSetting *group_id_setting = conf_setting_lookup_required(fiber_group_setting, "group_id");
            FiberGroupId group_id = fiber_group_id_from_string(conf_setting_get_string(group_id_setting));
            // verify the same fiber group hadn't been defined twice
            ASSERT_EQUAL(_scheduler_config.fiber_groups[(int)group_id].stack_size, 0);

            _scheduler_config.fiber_groups[(int)group_id].module_id = module_id;

            ConfigSetting *count_setting = conf_setting_lookup_required(fiber_group_setting, "count");
            _scheduler_config.fiber_groups[(int)group_id].fiber_count = conf_setting_get_int32(count_setting);
            ConfigSetting *stack_size_setting = conf_setting_lookup_required(fiber_group_setting, "stack_size");
            _scheduler_config.fiber_groups[(int)group_id].stack_size = (size_t) conf_setting_get_int32(
                stack_size_setting);
        }
    }

    ConfigSetting *trace_setting = conf_setting_lookup_required(silo_config, "traces");
    _trace_emitter.init(trace_setting, false);
    _trace_dumper.init(trace_setting, &_trace_emitter, trace_dir);
}

static void pin_to_core(int32_t core_id)
{
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core_id, &cpuset);

    pthread_t thread = pthread_self();
    // if the next line fails it means we have a core id in the config file that doesn't exist
    ASSERT_EQUAL(pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset), 0);
}

/*static*/ void Silo::start_modules_fiber_func(void *silo_arg)
{
    Silo *silo = (Silo *)silo_arg;
    silo->start_modules();
}

/*static*/ void Silo::maintenance_fiber_func(void *silo_arg)
{
    Silo *silo = (Silo *)silo_arg;
    silo->maintenance();
}

void Silo::maintenance()
{
    while (true) {
        P::TimerQueues::sleep(P::SleepInterval::SLEEP_1_SECOND);
        _trace_emitter.flush();
    }
}

void Silo::start_modules()
{
    Env::get()->wait_for_run_state();

    LOOP(ModuleId::COUNT, i) {
        if (_module_descriptors[i].defined) {
            PT_INFO(CONTROL, "Starting module: %s.", module_id_to_string((ModuleId) i));
            _module_descriptors[i].module->start();
        }
    }
}

Silo *Silo::get()
{
    return current_silo;
}

SiloId Silo::get_current_silo_id(void)
{
    Silo *silo = Silo::get();
    return silo != nullptr ? silo->get_id() : INVALID_SILO_ID;
}

/*static*/ void *Silo::main_func(void *silo_arg)
{
    Silo *silo = (Silo *) silo_arg;
    return silo->main();
}

void *Silo::main()
{
    if (_affinity != Silo::NO_AFFINITY)
        pin_to_core(_affinity);
    current_silo = this;

    _trace_emitter.set_local();
    _trace_dumper.start();

    PT_INFO(CONTROL, "Silo started. Affinity set to: %d.", _affinity);

    Scheduler::init(&_scheduler_config);
    ASSERT_NOT_NULL(Fiber::init((P::Index)FiberGroupId::E, start_modules_fiber_func, this, false));
    ASSERT_NOT_NULL(Fiber::init((P::Index)FiberGroupId::E, maintenance_fiber_func, this, false, true));
    Scheduler::run();
    // we shouldn't regularly get here. it means all fiber have finished running.
    Scheduler::destroy();

    PT_INFO(CONTROL, "Silo finished.");

    _trace_dumper.stop();
    _trace_dumper.wait();

    return nullptr;
}

void Silo::start()
{
    ASSERT_EQUAL(pthread_create(&_pthread, nullptr, main_func, this), 0);
}

void Silo::join()
{
    pthread_join(_pthread, nullptr);
}

Silo::ModuleDescriptor *Silo::get_module_descriptor()
{
    return &_module_descriptors[(int)Fiber::get_module_id()];
}

ModuleInterface *Silo::get_module()
{
    return Silo::get()->get_module_descriptor()->module;
}

void Silo::set_component_state(ModuleId module_id, ComponentId component_id, void *component)
{
    get_module_descriptor()->components[(int)component_id] = component;
}

void *Silo::get_component_state(ComponentId component_id)
{
    return get_module_descriptor()->components[(int)component_id];
}

void Silo::halt()
{
    _trace_dumper.stop();
    _trace_dumper.wait();

    if (_pthread)
        pthread_kill(_pthread, SIGTERM);
}

void Silo::destroy()
{
    _trace_dumper.destroy();
    _trace_emitter.destroy();
    delete[] _scheduler_config.fiber_groups;
}

}
