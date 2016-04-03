/* Copyright (C) Vast Data Ltd. */

/*!
 * Alternative implementations: https://swtch.com/libtask/amd64-ucontext.h
 * http://rethinkdb.com/blog/making-coroutines-fast/
 *
 * 1. Out of fibers.
 * 2. Removing while iterating gets stuck
 * 3. Iterating on -1 anchor
 */
#include <p.h>

typedef enum {
    STATE_INIT,
    STATE_READY,
    STATE_RUNNING,
    STATE_WAIT,
    STATE_DONE,
    STATE_COUNT
} p_fiber_state;

typedef struct p_scheduler p_scheduler;
struct p_scheduler {
    jmp_buf caller;
    p_pool *stacks;
    p_pool *fibers;
    p_dlist *queue;
    p_dlist_anchor states[STATE_COUNT];
    p_fiber_state last_state;
};

struct p_fiber {
    jmp_buf jmp_buf;
    //p_fiber_state state;
    void (*func)(void *arg);
    void *arg;
    void *stack;
};

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

#define STACK_SIZE 4096

static __thread p_fiber *current_fiber;
static __thread p_scheduler sched;

static __attribute__((noreturn)) void p_scheduler_continue();

static void fiber_destroy(p_fiber *fiber)
{
    p_pool_free(sched.stacks, p_pool_address_to_index(sched.stacks, fiber->stack));
    p_pool_free(sched.fibers, p_pool_address_to_index(sched.fibers, fiber));
}

static __attribute__((noreturn)) void fiber_main()
{
    current_fiber->func(current_fiber->arg);
    // We can't call fiber_destroy from here because we're still using the stack.
    p_dlist_append(sched.queue, &sched.states[STATE_DONE], p_pool_address_to_index(sched.fibers, current_fiber));
    p_scheduler_continue();
}

p_fiber *p_fiber_init(void (*func)(void *arg), void *arg)
{
    p_index fiber_index = p_pool_alloc(sched.fibers);
    p_fiber *fiber = p_pool_index_to_address(sched.fibers, fiber_index);
    void *stack = p_pool_alloc_address(sched.stacks);

    fiber->jmp_buf[0].__jmpbuf[JB_RSP] = ptr_mangle((intptr_t) stack + STACK_SIZE);
    fiber->jmp_buf[0].__jmpbuf[JB_PC] = ptr_mangle((intptr_t) fiber_main);
    fiber->stack = stack;
    fiber->func = func;
    fiber->arg = arg;

    p_dlist_append(sched.queue, &sched.states[STATE_INIT], fiber_index);
    return fiber;
}

void p_fiber_yield()
{
    if (!setjmp(current_fiber->jmp_buf)) {
        p_dlist_append(sched.queue, &sched.states[STATE_READY], p_pool_address_to_index(sched.fibers, current_fiber));
        p_scheduler_continue();
    }
}

static __attribute__((noreturn)) void p_fiber_run(p_fiber *fiber)
{
    current_fiber = fiber;
    longjmp(current_fiber->jmp_buf, true);
}

#define FIBERS 128

void p_scheduler_init()
{
    sched.stacks = p_pool_init(FIBERS, STACK_SIZE);
    sched.fibers = p_pool_init(FIBERS, sizeof(p_fiber));
    sched.queue = p_dlist_init(FIBERS);
    LOOP(STATE_COUNT, i) {
        sched.states[i] = P_DLIST_ANCHOR_INIT;
    }
    sched.last_state = STATE_INIT;
}

void p_scheduler_destroy()
{
    p_dlist_destroy(sched.queue);
    p_pool_destroy(sched.fibers);
    p_pool_destroy(sched.stacks);
}

static p_fiber_state get_next_state(p_fiber_state state)
{
    switch (state) {
    case STATE_INIT:
        return STATE_READY;
    case STATE_READY:
        return STATE_WAIT;
    case STATE_WAIT:
        return STATE_INIT;
    case STATE_DONE:
    case STATE_COUNT:
    case STATE_RUNNING:
    default:
        P_PANIC();
    }
}

static void free_done_fibers()
{
    p_index fiber_index = sched.states[STATE_DONE];
    while (fiber_index != P_DLIST_ANCHOR_INIT) {
        if (fiber_index == p_pool_address_to_index(sched.fibers, current_fiber)) {
            fiber_index = p_dlist_next(sched.queue, &sched.states[STATE_DONE], fiber_index);
            if (fiber_index == p_pool_address_to_index(sched.fibers, current_fiber))
                break;
        }
        fiber_destroy(p_pool_index_to_address(sched.fibers, fiber_index));
        p_dlist_remove(sched.queue, &sched.states[STATE_DONE], fiber_index);
        fiber_index = sched.states[STATE_DONE];
    }
}

static void p_scheduler_continue()
{
    free_done_fibers();

    p_index fiber_index;
    p_fiber_state state = sched.last_state;
    do {
        state = get_next_state(state);
        fiber_index = p_dlist_pop(sched.queue, &sched.states[state]);
        if (fiber_index != P_INVALID_INDEX) {
            sched.last_state = state;
            p_fiber_run(p_pool_index_to_address(sched.fibers, fiber_index));
        }
    } while(state != sched.last_state);

    // if we got here it means all the queues are empty
    longjmp(sched.caller, true);
}

void p_scheduler_run()
{
    if (!setjmp(sched.caller))
        p_scheduler_continue();
}
