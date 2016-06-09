/* Copyright (C) Vast Data Ltd. */

/*!
 * \file fiber.hpp
 * \brief The fiber API
 */
#pragma once

#include <setjmp.h>

#include "../utils/compiler.hpp"
#include "../memory/pool.hpp"
#include "../data/dlist.hpp"
#include "../sync/rwlock.hpp"
#include "../../vdefs.hpp"
#include "../../modules/module_interface.hpp"

namespace P {

struct FiberGroup {
    size_t stack_size;
    FiberGroup *next_group;
    Pool *stacks;
    ModuleId module_id;
    Index index;
    Index stacks_partition;
    DList::Anchor ready_queue;
};

class Fiber {

    friend class TimerQueues;

    enum class State: byte {
        READY,
        RUNNING,
        SUSPENDED,
        FREE
    };

    typedef union {
        uint32_t sem_count;
        uint32_t waited_future_count;
        Sync::RWlock::Type rw_lock_type;
    } SuspendState;

public:
    /*!
     * Initialize a fiber.
     *
     * \param group_index the index of the fiber_group (configured in Scheduler::init()).
     * \param func a function to be called when the fiber is started.
     * \param arg an argument to be passed to the func.
     * \return a pointer to a fiber or nullptr if the pool is empty.
     */
    static Fiber *init(Index group_index, void (*func)(void *arg), void *arg, bool parent_will_join);

    /*!
     * A fiber should call this function to yield the CPU. Should be used in CPU-intensive code.
     */
    static void yield();

    /*!
     * Block until all children finished.
     */
    static void join_all();

    /*!
     * Get the module id of the current running fiber (determined by its fiber group)
     */
    static ModuleId get_module_id();

    /*!
     * Return the currently running fiber.
     */
    static Fiber *get_current();

    /*!
     * Get the current/last job id performed by this fiber
     */
    uint32_t get_job_id();

    // the following functions are the internal API

    /*!
     * Resume a fiber. Should be used by providers or sync primitives.
     */
    void resume();

    /*!
     * Resume a fiber. Should be used by providers or sync primitives.
     * This function can be used to resume a fiber and deque it from a provider's
     * queue at the same time.
     */
    static Fiber *pop_and_resume(DList::Anchor *anchor);

    /*!
     * Get the next fiber to be popped without popping it.
     */
    static Fiber *queue_peek(DList::Anchor *anchor);

    /*!
     * Should be called from a provider or sync primitive in the context of a running fiber.
     */
    static void suspend(void);

    /*!
     * Should be called from a provider or sync primitive in the context of a running fiber.
     * This function accepts a queue argument for suspending the fiber and storing it in a queue at the same time.
     */
    static void suspend_and_queue(DList::Anchor *queue);

    /*!
     * Run a fiber. Should be called from the scheduler.
     */
    void run();

    /*!
     * Destroy a fiber and release its resources.
     */
    void destroy();

    SuspendState* get_suspend_state();

    static const uint64_t STACK_UNDERFLOW_MAGIC = 0xDEADBEEF;
    static const uint64_t STACK_OVERFLOW_MAGIC = 0xBABECAFE;

private:
    static void context_switch();
    static void NO_RETURN main();

    jmp_buf _jmp_buf;
    void (*_func)(void *arg);
    void *_arg;
    void *_stack;
    Fiber *_parent;
    FiberGroup *_group;
    uint64_t _switch_time; // updated when a fiber is resumed or suspended
    uint32_t _job_id;
    SuspendState _sus_state;
    uint32_t _join_count;
    State _state; // currently used for debug purposes
};

}
