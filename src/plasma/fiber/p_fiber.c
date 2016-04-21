/* Copyright (C) Vast Data Ltd. */

/*!
 * Alternative implementations: https://swtch.com/libtask/amd64-ucontext.h
 * http://rethinkdb.com/blog/making-coroutines-fast/
 *
 * 1. Expose a fiber_init + join interface.
 * 2. Wakeup time per group.
 * 3.
 */
#include <p.h>
#include <setjmp.h>
#include "p_fiber_internal.h"
#include "p_scheduler_internal.h"

#define STARVATION_THRESHOLD_NS 100000000 // 100 ms

PFiber *p_get_current_fiber()
{
    return p_get_scheduler()->current_fiber;
}

static void context_switch()
{
    PFiber *fiber = p_get_current_fiber();
    P_ASSERT(fiber->state != STATE_RUNNING);
    P_ASSERT(p_get_time_nano() - fiber->switch_time < STARVATION_THRESHOLD_NS);
    fiber->switch_time = p_get_time_nano();
    if (!setjmp(fiber->jmp_buf)) {
        p_scheduler_continue();
    }
}

static void __attribute__((noreturn)) fiber_main()
{
    PFiber *fiber = p_get_current_fiber();
    fiber->func(fiber->arg);

    if (fiber->parent != NULL)
        if (--fiber->parent->join_count == 0)
            p_fiber_resume(fiber->parent);
    p_fiber_destroy(fiber);
    // note that we're calling the scheduler using a stack we no longer own!
    // this is fine since no other thread has access to the stack and fiber pools.
    p_scheduler_continue();
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

void p_fiber_destroy(PFiber *fiber)
{
    PScheduler *sched = p_get_scheduler();
    p_pool_free(fiber->group->stacks, p_pool_address_to_index(fiber->group->stacks, fiber->stack));
    p_pool_free(sched->fiber_pool, p_pool_address_to_index(sched->fiber_pool, fiber));
    sched->running_fiber_count--;
}

PFiber *p_fiber_init(PIndex group_index, void (*func)(void *arg), void *arg)
{
    PScheduler *sched = p_get_scheduler();
    P_ASSERT(group_index < sched->group_count);
    PFiberGroup *group = &sched->groups[group_index];
    PIndex fiber_index = p_pool_partitioned_alloc(sched->fiber_pool, group_index);
    if (fiber_index == P_INVALID_INDEX)
        return NULL;
    PFiber *fiber = p_pool_index_to_address(sched->fiber_pool, fiber_index);
    void *stack = p_pool_partitioned_alloc_address(group->stacks, group->stacks_partition);
    // the stack grows downward so add the stack size and leave room for the instruction pointer.
    // the fiber will never return (it calls longjmp) so the instruction pointer is filled
    // with a magic value that helps identify to top of the stack when printing backtraces.
    void *stack_ptr = (void*) ((intptr_t) stack + (intptr_t) group->stack_size - (intptr_t) sizeof(uint64_t));
    uint64_t *stack_int_ptr = stack_ptr;
    *stack_int_ptr = (intptr_t) P_FIBER_STACK_UNDERFLOW_MAGIC;
    fiber->jmp_buf[0].__jmpbuf[JB_RSP] = ptr_mangle((intptr_t) stack_ptr);
    fiber->jmp_buf[0].__jmpbuf[JB_PC] = ptr_mangle((intptr_t) fiber_main);
    fiber->stack = stack;
    fiber->func = func;
    fiber->arg = arg;
    fiber->group = group;
    fiber->parent = NULL; // will be used by join

    p_fiber_resume(fiber);
    sched->running_fiber_count++;
    return fiber;
}

void p_fiber_yield()
{
    p_fiber_resume(p_get_current_fiber());
    context_switch();
}

void p_fiber_suspend()
{
    PFiber *fiber = p_get_current_fiber();
    fiber->state = STATE_SUSPENDED;
    context_switch();
}

void p_fiber_suspend_and_queue(PDlistAnchor *queue)
{
    PScheduler *sched = p_get_scheduler();
    p_dlist_append(sched->fiber_queue, queue, p_pool_address_to_index(sched->fiber_pool, sched->current_fiber));
    p_fiber_suspend();
}

void p_fiber_resume(PFiber *fiber)
{
    PScheduler *sched = p_get_scheduler();
    fiber->state = STATE_READY;
    p_dlist_append(sched->fiber_queue, &fiber->group->ready_queue, p_pool_address_to_index(sched->fiber_pool, fiber));
}

void p_fiber_resume_and_deque(PFiber *fiber, PDlistAnchor *anchor)
{
    PScheduler *sched = p_get_scheduler();
    p_dlist_remove(sched->fiber_queue, anchor, p_pool_address_to_index(sched->fiber_pool, fiber));
    p_fiber_resume(fiber);
}

void __attribute__((noreturn)) p_fiber_run(PFiber *fiber)
{
    PScheduler *sched = p_get_scheduler();
    sched->current_fiber = fiber;
    fiber->state = STATE_RUNNING;
    fiber->switch_time = p_get_time_nano();
    longjmp(fiber->jmp_buf, true);
}

void p_join(PFiber *fiber)
{
    p_join_init();
    p_join_add(fiber);
    p_join_all();
}

void p_join_init()
{
    p_get_current_fiber()->join_count = 0;
}

void p_join_add(PFiber *fiber)
{
    P_ASSERT(fiber->parent == NULL);
    fiber->parent = p_get_current_fiber();
    p_get_current_fiber()->join_count++;
}

void p_join_all()
{
    p_fiber_suspend();
}
