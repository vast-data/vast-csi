/* Copyright (C) Vast Data Ltd. */

/*!
 * \file silo.hpp
 * \brief a silo wraps a pthread and initializes our execution model (modules, components, fibers, etc')
 */
#pragma once

#include <stdint.h>
#include <limits.h>
#include <pthread.h>
#include "../fiber/scheduler.hpp"
#include "../trace/emitter.hpp"
#include "../trace/dumper.hpp"
#include "config.hpp"
#include "defs.hpp"

class ModuleInterface;

namespace P {

typedef uint8_t SiloId;

class Silo {
public:
    static const int32_t NO_AFFINITY = -1;
    static const SiloId  INVALID_SILO_ID = 255;

    /*!
     * Initialize a silo. Returns a pointer to a heap-allocated Silo object.
     *
     * \param affinity the core id this silo should be pinned to. NO_AFFINITY (-1) means this silo should not be pinned to any core.
     * \param silo_config a config subtree. Here's an example configuration:
     \code
     {
       modules: {
         MODULE_I: {
           components: {
             cache: {
               pages: 200;
             }
           }
           fibers: (
             {
               count: 50;
               stack_size: 4096;
               group_id: "FIBER_GROUP_P";
             }
           )
         }
       }
       traces: {

       }
     }
     \endcode
    */
    void init(P::Conf::ConfigSetting *silo_config, int32_t affinity, SiloId silo_id, const char *data_dir, const char *trace_dir);

    /*!
     * Launch a silo (starts a pthread) and return immediately.
     */
    void start();

    /*!
     * Return the currently running silo. Implemented using thread local storage.
     */
    static Silo *get();

    /*!
     * Return the id of the currently running silo.
     * If called by a non silo thread will return P_INVALID_SILO_ID
     */
    static SiloId get_current_silo_id();

    SiloId get_id() { return _silo_id; }

    /*!
     * Return a pointer to the current module. Determined by the current fiber's group.
     */
    static ModuleInterface *get_module();

    /*!
     * Save a pointer to a component's state, retrievable afterwards using get_component_state(). This function should be called from %_module_init.
     */
    void set_component_state(ModuleId module_id, ComponentId component_id, void *component);

    /*!
     * Return a pointer to a component's state previously saved by set_component_state() during %_module_init.
     */
    void *get_component_state(ComponentId component_id);

    /*!
    * This function waits for the silo to finish, this should never happen and is.
    * used solely for testing.
    */
    void join();

    /*!
     * This function dumps the silo's traces. Should be called before shutdown.
     */
    void finalize();

    /*!
     * This function releases the silo's resources. It's important to mention this is used solely for testing. When a silo is destroyed its resources are freed but the modules that it initialized will not be destroyed (module/components don't support destruction).
     */
    void destroy();

private:
    struct ModuleDescriptor {
        ModuleInterface *module;
        void *components[(int)ComponentId::COUNT];
        bool defined;
    };

    ModuleDescriptor *get_module_descriptor();

    static void maintenance_fiber_func(void *silo_arg);
    void maintenance();

    static void start_modules_fiber_func(void *silo_arg);
    void start_modules();

    static void *main_func(void *silo_arg);
    void *main();

private:
    ModuleDescriptor _module_descriptors[(int)ModuleId::COUNT];
    SchedulerConfig _scheduler_config;
    Trace::Emitter _trace_emitter;
    Trace::Dumper _trace_dumper;
    pthread_t _pthread;
    int32_t _affinity;
    SiloId _silo_id;
};

#define COMPONENT_GET_STATE() Silo::get()->get_component_state(CURRENT_COMPONENT)

}
