/* Copyright (C) Vast Data Ltd. */
//#define _GNU_SOURCE

#include "silo.hpp"

#include <sched.h>
#include <limits.h>
#include <signal.h>
#include <pthread.h>
#include <stdio.h>

#include <plasma/internal.h>
#include <plasma/memory/alloc.hpp>
#include "plasma/utils/macros.hpp"
#include "plasma/utils/os.hpp"
#include "vdefs.hpp"
#include "../fiber/fiber.hpp"
#include "config.hpp"
#include "env.hpp"
#include "../../modules/module_interface.hpp"

namespace P {

using namespace P::Conf;

static __thread Silo *current_silo = NULL;

void Silo::init(ConfigSetting *silo_config, int32_t affinity, SiloId silo_id, const char *data_dir)
{
    _affinity = affinity;
    _silo_id = silo_id;

    _scheduler_config.group_count = (P::Index)FiberGroupId::COUNT;
    _scheduler_config.fiber_groups =
        (FiberGroupConfig *) p_safe_malloc(sizeof(FiberGroupConfig) * _scheduler_config.group_count);
    p_fill_zeroes(_scheduler_config.fiber_groups, sizeof(FiberGroupConfig) * _scheduler_config.group_count);

    ConfigSetting *modules_setting = conf_setting_lookup_required(silo_config, "modules");
    LOOP(conf_setting_length(modules_setting), i) {
        ConfigSetting *module_setting = conf_setting_get_element(modules_setting, (uint32_t) i);
        const char *module_name = conf_setting_name(module_setting);

        ModuleId module_id;
        ModuleInterface *module = Env::get()->create_module(module_name, &module_id);
        _modules[(int)module_id].defined = true;
        _modules[(int)module_id].module = module;
        _modules[(int)module_id].user_state = module->init(this, module_setting);

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

    snprintf(_trace_dir_path, PATH_MAX, "%s/traces", data_dir);
    ensure_directory_exists(_trace_dir_path);

    ConfigSetting *trace_config = conf_setting_lookup_required(silo_config, "traces");
//    _trace_emitter = p_trace_emitter_init(trace_config);
//    _trace_dumper = p_trace_dumper_init(trace_config, _trace_emitter, _trace_dir_path);
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

void Silo::silo_start_in_fiber_func(void *silo_arg)
{
    Silo *silo = (Silo *)silo_arg;
    silo->silo_start_in_fiber();
}

void Silo::silo_start_in_fiber()
{
    Env::get()->wait_for_run_state();

    LOOP(ModuleId::COUNT, i) {
        if (_modules[i].defined) {
//            PT_INFO("Starting module: %s.", module_id_to_string((ModuleId) i));
            _modules[i].module->start();
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
    return silo != NULL ? silo->get_id() : INVALID_SILO_ID;
}

/*static*/ void *Silo::silo_main_func(void *silo_arg)
{
    Silo *silo = (Silo *) silo_arg;
    return silo->silo_main();
}

void *Silo::silo_main()
{
    if (_affinity != Silo::NO_AFFINITY)
        pin_to_core(_affinity);
    current_silo = this;

//    p_trace_emitter_set(_trace_emitter);
//    p_trace_dumper_start(_trace_dumper);

//    PT_INFO("Silo started. Affinity set to: %d.", _affinity);

    Scheduler::init(&_scheduler_config);
    Fiber::init((P::Index)FiberGroupId::P, silo_start_in_fiber_func, this, false);
    Scheduler::run();
    // we shouldn't regularly get here. it means all fiber have finished running.
    Scheduler::destroy();

//    PT_INFO("Silo finished.");

//    p_trace_dumper_stop(_trace_dumper);
//    p_trace_dumper_wait(_trace_dumper);

    return NULL;
}

void Silo::start()
{
    ASSERT_EQUAL(pthread_create(&_pthread, NULL, silo_main_func, this), 0);
}

void Silo::join()
{
    pthread_join(_pthread, NULL);
}

/*static*/ Silo::Module *Silo::get_module()
{
    return &Silo::get()->_modules[(int)Fiber::get_module_id()];
}

void *Silo::get_module_state()
{
    return get_module()->user_state;
}

void Silo::set_component_state(ModuleId module_id, ComponentId component_id, void *component)
{
    _modules[(int)module_id].components[(int)component_id] = component;
}

void *Silo::get_component_state(ComponentId component_id)
{
    return get_module()->components[(int)component_id];
}

void Silo::halt()
{
//    p_trace_dumper_stop(_trace_dumper);
//    p_trace_dumper_wait(_trace_dumper);

    pthread_kill(_pthread, SIGSTOP);
}

void Silo::destroy()
{
//    p_trace_dumper_destroy(_trace_dumper);
//    p_trace_emitter_destroy(_trace_emitter);
    p_free(_scheduler_config.fiber_groups);
}

}
