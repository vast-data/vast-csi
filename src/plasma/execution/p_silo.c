/* Copyright (C) Vast Data Ltd. */
#define _GNU_SOURCE

#include <sched.h>
#include <signal.h>
#include <pthread.h>

#include <p.h>

#include "p_config_internal.h"

typedef struct Module Module;
struct Module {
    void *user_state;
    void *components[COMPONENT_COUNT];
    bool defined;
};

struct PSilo {
    Module modules[MODULE_COUNT];
    PSchedulerConfig scheduler_config;
    pthread_t pthread;
    int32_t affinity;
    PSiloId silo_id;
};

PSilo *p_silo_init(PConfigSetting *silo_config, int32_t affinity, PSiloId silo_id)
{
    PSilo *silo = p_safe_malloc(sizeof(PSilo));
    p_fill_zeroes(silo, sizeof(PSilo));
    silo->affinity = affinity;
    silo->silo_id = silo_id;

    silo->scheduler_config.group_count = FIBER_GROUP_COUNT;
    silo->scheduler_config.fiber_groups = p_safe_malloc(sizeof(PFiberGroupConfig) * FIBER_GROUP_COUNT);
    p_fill_zeroes(silo->scheduler_config.fiber_groups, sizeof(PFiberGroupConfig) * FIBER_GROUP_COUNT);

    PConfigSetting *modules_setting = p_config_setting_lookup_required(silo_config, "modules");
    LOOP(p_config_setting_length(modules_setting), i) {
        PConfigSetting *module_setting = p_config_setting_get_element(modules_setting, (uint32_t) i);
        const char *module_name = p_config_setting_name(module_setting);

        ModuleId module_id = string_to_module_id(module_name);
        silo->modules[module_id].defined = true;
        silo->modules[module_id].user_state = module_init_functions[module_id](silo, module_setting);

        PConfigSetting *fibers_setting = p_config_setting_lookup_required(module_setting, "fibers");
        LOOP(p_config_setting_length(fibers_setting), j) {
            PConfigSetting *fiber_group_setting = p_config_setting_get_element(fibers_setting, (uint32_t) j);
            PConfigSetting *group_id_setting = p_config_setting_lookup_required(fiber_group_setting, "group_id");
            FiberGroupId group_id = string_to_fiber_group_id(p_config_setting_get_string(group_id_setting));
            // verify the same fiber group hadn't been defined twice
            P_ASSERT(silo->scheduler_config.fiber_groups[group_id].stack_size == 0);

            silo->scheduler_config.fiber_groups[group_id].module_id = module_id;

            PConfigSetting *count_setting = p_config_setting_lookup_required(fiber_group_setting, "count");
            silo->scheduler_config.fiber_groups[group_id].fiber_count = p_config_setting_get_int32(count_setting);
            PConfigSetting *stack_size_setting = p_config_setting_lookup_required(fiber_group_setting, "stack_size");
            silo->scheduler_config.fiber_groups[group_id].stack_size = (size_t) p_config_setting_get_int32(stack_size_setting);
        }
    }

    return silo;
}

static void pin_to_core(int32_t core_id)
{
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core_id, &cpuset);

    pthread_t thread = pthread_self();
    // if the next line fails it means we have a core id in the config file that doesn't exist
    P_ASSERT(pthread_setaffinity_np(thread, sizeof(cpu_set_t), &cpuset) == 0);
}

static void silo_start_in_fiber(void *silo_arg)
{
    env_wait_for_run_state();

    PSilo *silo = silo_arg;
    LOOP(MODULE_COUNT, i) {
        if (silo->modules[i].defined) {
            module_start_functions[i]();
        }
    }

}

static __thread PSilo *current_silo = NULL;

PSilo *p_silo_get()
{
    return current_silo;
}

PSiloId p_silo_get_id(void)
{
    PSilo *silo = p_silo_get();
    return silo != NULL ? silo->silo_id : P_INVALID_SILO_ID;
}


static void *silo_main(void *silo_arg)
{
    PSilo *silo = silo_arg;
    if (silo->affinity != NO_AFFINITY)
        pin_to_core(silo->affinity);
    current_silo = silo;
    p_scheduler_init(&silo->scheduler_config);
    p_fiber_init(FIBER_GROUP_P, silo_start_in_fiber, silo, false);
    p_scheduler_run();
    // we shouldn't regularly get here. it means all fiber have finished running.
    p_scheduler_destroy();
    return NULL;
}

void p_silo_start(PSilo *silo)
{
    P_ASSERT(pthread_create(&silo->pthread, NULL, silo_main, silo) == 0);
}

void p_silo_join(PSilo *silo)
{
    pthread_join(silo->pthread, NULL);
}

static Module *get_module()
{
    return &p_silo_get()->modules[p_fiber_get_module_id()];
}

void *p_get_module_state()
{
    return get_module()->user_state;
}

void p_silo_set_component_state(PSilo *silo, ModuleId module_id, ComponentId component_id, void *component)
{
    silo->modules[module_id].components[component_id] = component;
}

void *p_silo_get_component_state(ComponentId component_id)
{
    return get_module()->components[component_id];
}

void p_silo_halt(PSilo *silo)
{
    pthread_kill(silo->pthread, SIGSTOP);
}

void p_silo_destroy(PSilo *silo)
{
    p_free(silo->scheduler_config.fiber_groups);
    p_free(silo);
}
