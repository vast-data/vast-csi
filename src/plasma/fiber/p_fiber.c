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

p_fiber *p_get_current_fiber()
{
    return p_get_scheduler()->current_fiber;
}

static void context_switch()
{
    p_fiber *fiber = p_get_current_fiber();
    P_ASSERT(fiber->state != STATE_RUNNING);
    P_ASSERT(p_get_time_nano() - fiber->switch_time < STARVATION_THRESHOLD_NS);
    fiber->switch_time = p_get_time_nano();
    if (!setjmp(fiber->jmp_buf)) {
        p_scheduler_continue();
    }
}

static void __attribute__((noreturn)) fiber_main()
{
    p_fiber *fiber = p_get_current_fiber();
    fiber->func(fiber->arg);

    if (fiber->parent != NULL)
        if (--fiber->parent->join_count == 0)
            p_scheduler_change_fiber_state(fiber->parent, STATE_READY);
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

void p_fiber_destroy(p_fiber *fiber)
{
    p_pool_free(fiber->group->stacks, p_pool_address_to_index(fiber->group->stacks, fiber->stack));
    p_pool_free(fiber->group->fibers, p_pool_address_to_index(fiber->group->fibers, fiber));
}

p_fiber *p_fiber_init(size_t group_index, void (*func)(void *arg), void *arg)
{
    P_ASSERT(group_index < p_get_scheduler()->group_count);
    p_fiber_group *group = &p_get_scheduler()->groups[group_index];
    p_index fiber_index = p_pool_alloc(group->fibers);
    if (fiber_index == P_INVALID_INDEX)
        return NULL;
    p_fiber *fiber = p_pool_index_to_address(group->fibers, fiber_index);
    void *stack = p_pool_alloc_address(group->stacks);

    fiber->jmp_buf[0].__jmpbuf[JB_RSP] = ptr_mangle((intptr_t) stack + (intptr_t) group->stack_size);
    fiber->jmp_buf[0].__jmpbuf[JB_PC] = ptr_mangle((intptr_t) fiber_main);
    fiber->stack = stack;
    fiber->func = func;
    fiber->arg = arg;
    fiber->group = group;
    fiber->parent = NULL; // will be used by join

    p_scheduler_set_fiber_state(fiber, STATE_READY);
    return fiber;
}

void p_fiber_yield()
{
    p_fiber_resume(p_get_current_fiber());
    context_switch();
}

void p_fiber_suspend(p_fiber_state state)
{
    p_scheduler_set_fiber_state(p_get_current_fiber(), state);
    context_switch();
}

void p_fiber_resume(p_fiber *fiber)
{
    p_scheduler_set_fiber_state(fiber, STATE_READY);
}

void __attribute__((noreturn)) p_fiber_run(p_fiber *fiber)
{
    p_scheduler *scheduler = p_get_scheduler();
    scheduler->current_fiber = fiber;
    fiber->state = STATE_RUNNING;
    fiber->switch_time = p_get_time_nano();
    longjmp(fiber->jmp_buf, true);
}

void p_join(p_fiber *fiber)
{
    p_join_init();
    p_join_add(fiber);
    p_join_all();
}

void p_join_init()
{
    p_get_current_fiber()->join_count = 0;
}

void p_join_add(p_fiber *fiber)
{
    P_ASSERT(fiber->parent == NULL);
    fiber->parent = p_get_current_fiber();
    p_get_current_fiber()->join_count++;
}

void p_join_all()
{
    p_fiber_suspend(STATE_JOIN);
}
