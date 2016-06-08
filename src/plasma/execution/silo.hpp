/* Copyright (C) Vast Data Ltd. */

/*!
 * \file silo.hpp
 * \brief a silo wraps a pthread and initializes our execution model (modules, components, fibers, etc')
 */
#pragma once

#include <stdint.h>
#include <limits.h>
#include <pthread.h>
#include <modules/module_interface.hpp>

//#include "../trace/emitter.h"
//#include "../trace/dumper.h"
#include "../vdefs.hpp"
#include "../fiber/p_scheduler.h"
#include "config.hpp"

namespace P {

typedef uint8_t SiloId;

/*!
 * Initialize a silo. Returns a pointer to a heap-allocated PSilo object.
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

class Silo {
public:
    static const int32_t NO_AFFINITY = -1;
    static const SiloId  INVALID_SILO_ID = 255;

    void init(P::Conf::ConfigSetting *silo_config, int32_t affinity, SiloId silo_id, const char *data_dir);

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
     * Return the current module state. Each module sets the state with the return value of %_module_init. The current module is determined by the fiber group of the currently runnning fiber (each fiber group belongs to a module).
     */
    static void *get_module_state();

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
     * This function halts a silo (stops its pthread with SIGSTOP).
     * The main use case is for debugging: when a thread segfaults all other threads are stopped.
     */
    void halt();

    /*!
     * This function releases the silo's resources. It's important to mention this is used solely for testing. When a silo is destroyed its resources are freed but the modules that it initialized will not be destroyed (module/components don't support destruction).
     */
    void destroy();

private:
    typedef struct Module {
        ModuleInterface *module;
        void *user_state;
        void *components[(int)ComponentId::COUNT];
        bool defined;
    } Module;

    static Module *get_module();

    static void silo_start_in_fiber_func(void *silo_arg);
    void silo_start_in_fiber();

    static void *silo_main_func(void *silo_arg);
    void *silo_main();

private:
    Module _modules[(int)ModuleId::COUNT];
    PSchedulerConfig _scheduler_config;
    char _trace_dir_path[PATH_MAX];
//    PTraceEmitter *_trace_emitter;
//    PTraceDumper *_trace_dumper;
    pthread_t _pthread;
    int32_t _affinity;
    SiloId _silo_id;
};

#define COMPONENT_GET_STATE() Silo::get()->get_component_state(CURRENT_COMPONENT)

}