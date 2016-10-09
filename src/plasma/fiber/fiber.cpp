/* Copyright (C) Vast Data Ltd. */

/*!
 * Alternative implementations: https://swtch.com/libtask/amd64-ucontext.h,
 * http://rethinkdb.com/blog/making-coroutines-fast/
 */
#include <sys/mman.h>

#include "fiber.hpp"

#include "globals.hpp"
#include "scheduler.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/utils/compiler.hpp"
#include "plasma/utils/time.hpp"
#include "plasma/internal.hpp"

namespace P {

static const uint64_t STARVATION_THRESHOLD_NS = 100000000; // 100 ms

/* static */ Fiber *Fiber::get_current()
{
    Scheduler *sched = Scheduler::get();
    if (sched == nullptr)
        return nullptr;
    return sched->_current_fiber;
}

/* static */ ModuleId Fiber::get_module_id()
{
    return get_current()->_group->module_id;
}

uint64_t Fiber::get_switch_time()
{
    return _switch_time;
}

/* static */ void Fiber::context_switch()
{
    Fiber *fiber = Fiber::get_current();
    ASSERT(fiber->_state != State::RUNNING, "Cannot suspend a fiber that isn't running");
    if (likely(!global_debugging)) {
        // don't want to measure time while debugging
        ASSERT_OP(P::get_time_nano() - fiber->_switch_time, <, STARVATION_THRESHOLD_NS, "Fiber took longer than expected");
    }
    ASSERT_EQUAL(*((intptr_t *) fiber->_stack), (intptr_t) STACK_OVERFLOW_MAGIC);

    fiber->_switch_time = P::get_time_nano();
    if (!setjmp(fiber->_jmp_buf)) {
        Scheduler::schedule();
    }
}

/* static */ void NO_RETURN Fiber::main()
{
    Fiber *fiber = Fiber::get_current();
    fiber->_func(fiber->_arg);

    if (fiber->_parent != nullptr)
        if (--fiber->_parent->_join_count == 0)
            fiber->_parent->resume();

    // We must join children before we die
    ASSERT_EQUAL(fiber->_join_count, 0);

    fiber->destroy();
    // note that we're calling the scheduler using a stack we no longer own!
    // this is fine since no other thread has access to the stack and fiber pools.
    Scheduler::schedule();
}

// The following attributes were found in glibc/sysdeps/x86_64/jmpbuf-offsets.h
#define JB_RSP 6
#define JB_PC 7

/*!
 * libc does a thing called pointer encryption or pointer mangling when implementing set/long jumps.
 * the mangling is implemented by xoring the address with a per-executable key and rotating the bits.
 *
 * Where can this code be found:
 * 1. Disassemble libc (it's simpler than reading the relevant libc source): objdump -d /lib64/libc.so.6
 * 2. Look for the __sigsetjmp implementation.
 * 3. Look for a 'xor' and 'rol' pair.
 */
static intptr_t ptr_mangle(intptr_t addr)
{
    intptr_t ret;
    __asm__ volatile("xor %%fs:0x30,%0\n" // %fs is a register segment, at offset 0x30 lies the key
                     "rol $0x11,%0" // rotate the register 0x11 bits
                     : "=g" (ret)
                     : "0" (addr));
    return ret;
}

void Fiber::destroy()
{
    Scheduler *sched = Scheduler::get();
#ifdef DEBUG
    _stack = (char*)_stack - PAGE_SIZE_BYTES;
    ASSERT_EQUAL(mprotect(_stack, PAGE_SIZE_BYTES, PROT_READ|PROT_WRITE), 0, "errno = " << errno);
#endif
    _group->stacks->partitioned_free_address(_stack, _group->stacks_partition);
    sched->_fiber_pool.partitioned_free_address(this, _group->index);
    if (!_daemon)
        sched->_running_fiber_count--;
}

uint32_t Fiber::get_job_id()
{
    return _job_id;
}

/* static */
Fiber *Fiber::init(Index group_index, void (*func)(void *arg), void *arg, bool parent_will_join, bool daemon)
{
    Scheduler *sched = Scheduler::get();
    DEBUG_ASSERT_OP(group_index, <, sched->_group_count, "out of bounds group index");
    FiberGroup *group = &sched->_groups[group_index];
    Index fiber_index = sched->_fiber_pool.partitioned_alloc(group_index);
    if (fiber_index == INVALID_INDEX) {
        PT_WARN(DATA, "Out of fibers for fiber_group=%d", group_index);
        return nullptr;
    }
    Fiber *fiber = (Fiber*) sched->_fiber_pool.index_to_address(fiber_index);
    void *stack = group->stacks->partitioned_alloc_address(group->stacks_partition);
#ifdef DEBUG
    if (!daemon) {  // TODO: see ORION-91.
        ASSERT_EQUAL(mprotect(stack, PAGE_SIZE_BYTES, PROT_NONE), 0, "errno = " << errno);
        stack = (char*)stack + PAGE_SIZE_BYTES;
    }
#endif
    uint64_t *stack_int_ptr = (uint64_t*) stack;
    *stack_int_ptr = (intptr_t) STACK_OVERFLOW_MAGIC;
    // the stack grows downward so add the stack size and leave room for the instruction pointer.
    // the fiber will never return (it calls longjmp) so the instruction pointer is filled
    // with a magic value that helps identify to top of the stack when printing backtraces.
    void *stack_ptr = (void*) ((intptr_t) stack + (intptr_t) group->stack_size - (intptr_t) sizeof(uint64_t));
    stack_int_ptr = (uint64_t*) stack_ptr;
    *stack_int_ptr = (intptr_t) STACK_UNDERFLOW_MAGIC;
    fiber->_jmp_buf[0].__jmpbuf[JB_RSP] = ptr_mangle((intptr_t) stack_ptr);
    fiber->_jmp_buf[0].__jmpbuf[JB_PC] = ptr_mangle((intptr_t) main);
    fiber->_stack = stack;
    fiber->_func = func;
    fiber->_arg = arg;
    fiber->_group = group;
    fiber->_daemon = daemon;
    fiber->_job_id = ++Scheduler::get()->_curr_job_id;
    fiber->_parent = nullptr; // will be used by join
    fiber->_join_count = 0;
    if (parent_will_join) {
        fiber->_parent = get_current();
        fiber->_parent->_join_count++;
    }

#ifdef DEBUG
    fiber-> _owner_sched = sched;
#endif

    fiber->resume();
    if (!daemon)
        sched->_running_fiber_count++;
    return fiber;
}

/* static */ void Fiber::yield()
{
    get_current()->resume();
    context_switch();
}

/* static */ void Fiber::thread_or_fiber_yield()
{
    if (is_fiber()) {
        yield();
    } else {
        int ret = sched_yield();
        ASSERT_EQUAL(ret, 0);
    }
}

/* static */ bool Fiber::is_fiber()
{
    return Scheduler::get() != nullptr;
}

/* static */ void Fiber::suspend()
{
    Fiber *fiber = get_current();
    fiber->_state = State::SUSPENDED;
    context_switch();
}

/* static */ void Fiber::suspend_and_queue(DList::Anchor *anchor)
{
    Scheduler *sched = Scheduler::get();
    DList queue;
    queue.init(anchor, &sched->_fiber_queues);
    queue.append(sched->_fiber_pool.address_to_index(sched->_current_fiber));
    Fiber::suspend();
}

void Fiber::resume()
{
    Scheduler *sched = Scheduler::get();
    DEBUG_ASSERT(_owner_sched == sched);
    _state = State::READY;
    DList queue;
    queue.init(&_group->ready_queue, &sched->_fiber_queues);
    queue.append(sched->_fiber_pool.address_to_index(this));
    ++sched->_ready_fiber_count;
}

/* static */ Fiber *Fiber::queue_peek(DList::Anchor *anchor)
{
    Scheduler *sched = Scheduler::get();
    DList queue;
    queue.init(anchor, &sched->_fiber_queues);
    if (queue.is_empty())
        return nullptr;
    return (Fiber*) sched->_fiber_pool.index_to_address(queue.get_first());
}

/* static */ Fiber *Fiber::pop_and_resume(DList::Anchor *anchor)
{
    Fiber *fiber = queue_peek(anchor);
    if (fiber == nullptr) {
        return nullptr;
    }
    Scheduler *sched = Scheduler::get();
    DList queue;
    queue.init(anchor, &sched->_fiber_queues);
    Index popped_idx = queue.pop();
    ASSERT_EQUAL(popped_idx, sched->_fiber_pool.address_to_index(fiber));
    fiber->resume();
    return fiber;
}

void NO_RETURN Fiber::run()
{
    Scheduler *sched = Scheduler::get();
    sched->_current_fiber = this;
    _state = State::RUNNING;
    _switch_time = P::get_time_nano();
    longjmp(_jmp_buf, true);
}

/* static */ void Fiber::join_all()
{
    // make sure there is a child fiber that will perform resume
    if (get_current()->_join_count > 0) {
        suspend();
    }
}

}  // namespace P
