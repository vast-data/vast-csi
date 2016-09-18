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
#include "sync/rwlock.hpp"
#include "../../defs.hpp"
#include "sleep.hpp"

namespace P {

class Scheduler;

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
    typedef union {
        uint32_t sem_count;
        uint32_t waited_future_count;
        FiberSync::RWlock::Type rw_lock_type;
        SleepInterval sleep_interval;
    } SuspendState;

public:
    enum class State: byte {
        // TODO: consider enriching this enum (e.g. add sub-types for SUSPENDED - SLEEP, LOCK, etc.).
        READY,
        RUNNING,
        SUSPENDED,
        FREE
    };

    /*!
     * Initialize a fiber.
     *
     * \param group_index the index of the fiber_group (configured in Scheduler::init()).
     * \param func a function to be called when the fiber is started.
     * \param arg an argument to be passed to the func.
     * \param parent_will_join when true, notifies a joining parent and potentially resuming it (if this child is the last)
     * \param daemon when true, the scheduler doesn't wait for this fiber to finish in order to exit
     * \return a pointer to a fiber or nullptr if the pool is empty.
     */
    static Fiber *init(Index group_index, void (*func)(void *arg), void *arg, bool parent_will_join=false, bool daemon=false);

    /*!
     * A fiber should call this function to yield the CPU. Should be used in CPU-intensive code.
     */
    static void yield();

    /*!
     * Performs fiber yield for calling fibers and pthread_yield for other threads.
     */
    static void thread_or_fiber_yield();

    /*!
     * Determine if the calling thread is performed under the fiber context (running a scheduler run).
     */
    static bool is_fiber();

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
     * Get the time the fiber started/finished execution.
     */
    uint64_t get_switch_time();

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
    static void suspend();

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

    SuspendState* get_suspend_state() { return &_sus_state; }
    const State& get_state() const { return _state; }

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
    State _state;
    bool _daemon;

#ifdef DEBUG
    Scheduler *_owner_sched;
#endif
};  // class Fiber

}  // namespace P
