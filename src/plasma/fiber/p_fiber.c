/* Copyright (C) Vast Data Ltd. */

/*!
 * Alternative implementations: https://swtch.com/libtask/amd64-ucontext.h
 * http://rethinkdb.com/blog/making-coroutines-fast/
 *
 * 1. Out of fibers.
 * 2. Share stacks.
 * 3.
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

typedef struct p_fiber_group p_fiber_group;
struct p_fiber_group {
    p_pool *stacks;
    p_pool *fibers;
    p_dlist *queue;
    p_dlist_anchor states[STATE_COUNT];
    p_fiber_state last_state;
    size_t stack_size;
};

typedef struct p_scheduler p_scheduler;
struct p_scheduler {
    jmp_buf caller;
    size_t group_count;
    size_t last_group;
    p_fiber_group *groups;
};

struct p_fiber {
    jmp_buf jmp_buf;
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

static __thread p_fiber *current_fiber;
static __thread p_scheduler sched;

static __attribute__((noreturn)) void p_scheduler_continue();

static void fiber_destroy(p_fiber_group *group, p_fiber *fiber)
{
    p_pool_free(group->stacks, p_pool_address_to_index(group->stacks, fiber->stack));
    p_pool_free(group->fibers, p_pool_address_to_index(group->fibers, fiber));
}

static __attribute__((noreturn)) void fiber_main()
{
    current_fiber->func(current_fiber->arg);
    // We can't call fiber_destroy from here because we're still using the stack.
    p_dlist_append(sched.groups[sched.last_group].queue, &sched.groups[sched.last_group].states[STATE_DONE], p_pool_address_to_index(sched.groups[sched.last_group].fibers, current_fiber));
    p_scheduler_continue();
}

p_fiber *p_fiber_init(size_t group_index, void (*func)(void *arg), void *arg)
{
    P_ASSERT(group_index < sched.group_count);
    p_index fiber_index = p_pool_alloc(sched.groups[group_index].fibers);
    p_fiber *fiber = p_pool_index_to_address(sched.groups[group_index].fibers, fiber_index);
    void *stack = p_pool_alloc_address(sched.groups[group_index].stacks);

    fiber->jmp_buf[0].__jmpbuf[JB_RSP] = ptr_mangle((intptr_t) stack + (intptr_t) sched.groups[sched.last_group].stack_size);
    fiber->jmp_buf[0].__jmpbuf[JB_PC] = ptr_mangle((intptr_t) fiber_main);
    fiber->stack = stack;
    fiber->func = func;
    fiber->arg = arg;

    p_dlist_append(sched.groups[group_index].queue, &sched.groups[group_index].states[STATE_INIT], fiber_index);
    return fiber;
}

void p_fiber_yield()
{
    if (!setjmp(current_fiber->jmp_buf)) {
        p_dlist_append(sched.groups[sched.last_group].queue, &sched.groups[sched.last_group].states[STATE_READY], p_pool_address_to_index(sched.groups[sched.last_group].fibers, current_fiber));
        p_scheduler_continue();
    }
}

static __attribute__((noreturn)) void p_fiber_run(p_fiber *fiber)
{
    current_fiber = fiber;
    longjmp(current_fiber->jmp_buf, true);
}

void p_scheduler_init(p_scheduler_config *config)
{
    sched.last_group = 0;
    sched.group_count = config->group_count;
    sched.groups = p_safe_cache_aligned_alloc(sizeof(p_fiber_group) * sched.group_count);

    p_fiber_group_config *fiber_config;
    p_fiber_group *fiber_group;

    LOOP(sched.group_count, i) {
        fiber_config = &config->fiber_groups[i];
        fiber_group = &sched.groups[i];
        fiber_group->stack_size = fiber_config->stack_size;
        fiber_group->stacks = p_pool_init(fiber_config->fiber_count, fiber_config->stack_size);
        fiber_group->fibers = p_pool_init(fiber_config->fiber_count, sizeof(p_fiber));
        fiber_group->queue = p_dlist_init(fiber_config->fiber_count);
        LOOP(STATE_COUNT, j) {
            fiber_group->states[j] = P_DLIST_ANCHOR_INIT;
        }
        fiber_group->last_state = STATE_INIT;
    }
}

void p_scheduler_destroy()
{
    p_fiber_group *fiber_group;
    LOOP(sched.group_count, i) {
        fiber_group = &sched.groups[i];
        p_dlist_destroy(fiber_group->queue);
        p_pool_destroy(fiber_group->fibers);
        if (fiber_group->stacks != NULL) {
            LOOP(sched.group_count, j)
                if (i != j && sched.groups[j].stacks == fiber_group->stacks)
                    sched.groups[j].stacks = NULL;
            p_pool_destroy(fiber_group->stacks);
        }
    }
    p_free(sched.groups);
}

static void free_done_fibers(p_fiber_group *fiber_group)
{
    p_index fiber_index = fiber_group->states[STATE_DONE];
    while (fiber_index != P_DLIST_ANCHOR_INIT) {
        if (fiber_index == p_pool_address_to_index(fiber_group->fibers, current_fiber)) {
            fiber_index = p_dlist_next(fiber_group->queue, &fiber_group->states[STATE_DONE], fiber_index);
            if (fiber_index == p_pool_address_to_index(fiber_group->fibers, current_fiber))
                break; // there's only one fiber and it's the one currently running
        }
        fiber_destroy(fiber_group, p_pool_index_to_address(fiber_group->fibers, fiber_index));
        p_dlist_remove(fiber_group->queue, &fiber_group->states[STATE_DONE], fiber_index);
        fiber_index = fiber_group->states[STATE_DONE];

    }
}

static void p_scheduler_continue()
{
    p_fiber_state state;
    p_index fiber_index;
    size_t fiber_group_index = sched.last_group;
    p_fiber_group *fiber_group;
    do {
        fiber_group_index = (fiber_group_index + 1) % sched.group_count;
        fiber_group = &sched.groups[fiber_group_index];
        free_done_fibers(fiber_group);
        state = sched.groups[fiber_group_index].last_state;
        do {
            state = state == STATE_INIT ? STATE_READY : STATE_INIT;
            fiber_index = p_dlist_pop(fiber_group->queue, &fiber_group->states[state]);
            if (fiber_index != P_INVALID_INDEX) {
                fiber_group->last_state = state;
                sched.last_group = fiber_group_index;
                p_fiber_run(p_pool_index_to_address(fiber_group->fibers, fiber_index));
            }
        } while(state != fiber_group->last_state);
    } while (fiber_group_index != sched.last_group);
    // if we got here it means all the queues are empty, return to the user
    longjmp(sched.caller, true);
}

void p_scheduler_run()
{
    if (!setjmp(sched.caller))
        p_scheduler_continue();
}
