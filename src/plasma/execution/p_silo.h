/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_silo.h
 * \brief a silo wraps a pthread and initializes our execution model (modules, components, fibers, etc')
 */
#pragma once

#include <p.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NO_AFFINITY -1

typedef struct PSilo PSilo;
typedef uint8_t PSiloId;
#define P_INVALID_SILO_ID (255)

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
PSilo *p_silo_init(PConfigSetting *silo_config, int32_t affinity, PSiloId silo_id, const char *data_dir);

/*!
 * Launch a silo (starts a pthread) and return immediately.
 */
void p_silo_start(PSilo *silo);

/*!
 * Return the currently running silo. Implemented using thread local storage.
 */
PSilo *p_silo_get(void);

/*!
 * Return the id of the currently running silo.
 * If called by a non silo thread will return P_INVALID_SILO_ID
 */
PSiloId p_silo_get_id(void);

/*!
 * Return the current module state. Each module sets the state with the return value of %_module_init. The current module is determined by the fiber group of the currently runnning fiber (each fiber group belongs to a module).
 */
void *p_get_module_state(void);

/*!
 * Save a pointer to a component's state, retreivable afterwards using p_silo_get_component_state(). This function should be called from %_module_init.
 */
void p_silo_set_component_state(PSilo *silo, ModuleId module_id, ComponentId component_id, void *component);

/*!
 * Return a pointer to a component's state previously saved by p_silo_set_component_state() during %_module_init.
 */
void *p_silo_get_component_state(ComponentId component_id);

/*!
 * This function waits for the silo to finish, this should never happen and is.
 * used solely for testing.
 */
void p_silo_join(PSilo *silo);

/*!
 * This function halts a silo (stops its pthread with SIGSTOP).
 * The main use case is for debugging: when a thread segfaults all other threads are stopped.
 */
void p_silo_halt(PSilo *silo);

/*!
 * This function releases the silo's resources. It's important to mention this is used solely for testing. When a silo is destroyed its resources are freed but the modules that it initialized will not be destroyed (module/components don't support destruction).
 */
void p_silo_destroy(PSilo *silo);

#define COMPONENT_GET_STATE() p_silo_get_component_state(CURRENT_COMPONENT)

#ifdef __cplusplus
}
#endif
