/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

static void increment(void *value)
{
    int *num_ptr = value;
    LOOP(3, i) {
        (*num_ptr)++;
        p_fiber_yield();
    }
}

#define PAGE_SIZE 4096
static PFiberGroupConfig fiber_groups[] = {
    {.fiber_count = 0, .stack_size = 0},
    {.fiber_count = 40, .stack_size = PAGE_SIZE * 16},
    {.fiber_count = 30, .stack_size = PAGE_SIZE * 8},
    {.fiber_count = 20, .stack_size = PAGE_SIZE * 8}
};
static PSchedulerConfig scheduler_config = {
    .fiber_groups = fiber_groups, .group_count = NUM_ELEMENTS(fiber_groups)
};

enum test_fiber_group {
    FG_EMPTY,
    FG_A,
    FG_B,
    FG_C
};

static void test_yield(void **state UNUSED)
{
    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, increment, &value, false);
    p_fiber_init(FG_B, increment, &value, false);
    p_fiber_init(FG_B, increment, &value, false);
    p_fiber_init(FG_C, increment, &value, false);
    p_scheduler_run();
    p_scheduler_destroy();

    assert_int_equal(value, 12);
}

static void increment_twice_serial(void *value)
{
    int *num_ptr = value;
    PFiber *f1, *f2;
    f1 = p_fiber_init(FG_A, increment, value, true);
    p_fiber_join_all();
    f2 = p_fiber_init(FG_A, increment, value, true);
    p_fiber_join_all();
    
    assert_int_equal(*num_ptr, 6);
}

static void test_join_single(void **state UNUSED)
{
    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, increment_twice_serial, &value, false);
    p_scheduler_run();
    p_scheduler_destroy();

    assert_int_equal(value, 6);
}

static void increment_twice_parallel(void *value)
{
    int *num_ptr = value;
    PFiber *f1, *f2;
    f1 = p_fiber_init(FG_A, increment, value, true);
    f2 = p_fiber_init(FG_A, increment, value, true);

    p_fiber_join_all();
    assert_int_equal(*num_ptr, 6);
    (*num_ptr)++;
}

static void test_join_all(void **state UNUSED)
{
    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, increment_twice_parallel, &value, false);
    p_scheduler_run();
    p_scheduler_destroy();

    assert_int_equal(value, 7);
}

static void first_sleeper(void *arg)
{
    int *value = arg;
    assert_in_range(p_sleep(SLEEP_100_MILLI), 100000, 110000);
    *value = 1;
    assert_in_range(p_sleep_multi(SLEEP_100_MILLI, 2), 200000, 220000);
    assert_int_equal(*value, 2);
    *value = 3;
}

static void second_sleeper(void *arg)
{
    int *value = arg;
    assert_in_range(p_sleep_multi(SLEEP_100_MILLI, 2), 200000, 220000);
    assert_int_equal(*value, 1);
    *value = 2;
}

static void test_sleep(void **state UNUSED)
{
    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, first_sleeper, &value, false);
    p_fiber_init(FG_A, second_sleeper, &value, false);

    p_scheduler_run();
    assert_int_equal(value, 3);

    p_scheduler_destroy();
}

static void fast_sleeper(void *arg)
{
    int *value = arg;

    assert_in_range(p_fast_sleep(1000), 1000, 1500);

    *value = 1;
}

static void test_fast_sleep(void **state UNUSED)
{
    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, fast_sleeper, &value, false);

    p_scheduler_run();
    assert_int_equal(value, 1);

    p_scheduler_destroy();
}

static int qlock_step = 0;

static void first_qlocker(void *lock_arg)
{
    PQlock *lock = lock_arg;

    assert_int_equal(qlock_step++, 0);
    p_qlock_lock(lock); // doesn't block
    assert_int_equal(qlock_step++, 1);
    p_fiber_yield();
    p_fiber_yield();
    assert_int_equal(qlock_step++, 3);
    p_qlock_unlock(lock);
}

static void second_qlocker(void *lock_arg)
{
    PQlock *lock = lock_arg;

    assert_int_equal(qlock_step++, 2);
    assert_false(p_qlock_trylock(lock));
    p_qlock_lock(lock); // blocks!
    assert_int_equal(qlock_step++, 4);
    p_qlock_unlock(lock);
}

static void test_qlock(void **state UNUSED)
{
    PQlock lock;
    p_qlock_init(&lock);

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, first_qlocker, &lock, false);
    p_fiber_init(FG_A, second_qlocker, &lock, false);

    p_qlock_destroy(&lock);

    p_scheduler_run();
    p_scheduler_destroy();
}

static int rwlock_state = 0;

static void write_locker(void *lock_arg)
{
    PRWlock *lock = lock_arg;

    assert_int_equal(rwlock_state++, 0);

    p_rwlock_lock_write(lock);

    assert_int_equal(rwlock_state++, 1);

    LOOP(100, i)
        p_fiber_yield();

    p_rwlock_unlock(lock);

    assert_int_equal(rwlock_state++, 5);
}

static void read_locker(void *lock_arg)
{
    PRWlock *lock = lock_arg;

    assert_in_range(rwlock_state++, 1, 4); // 3 fibers

    p_rwlock_lock_read(lock);

    assert_in_range(rwlock_state++, 6, 8); // 3 fibers

    p_rwlock_unlock(lock);
}

static void test_rwlock_barrier(void **state UNUSED)
{
    PRWlock lock;
    p_rwlock_init(&lock);

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, write_locker, &lock, false);
    p_fiber_init(FG_A, read_locker, &lock, false);
    p_fiber_init(FG_A, read_locker, &lock, false);
    p_fiber_init(FG_A, read_locker, &lock, false);
    p_scheduler_run();

    p_rwlock_destroy(&lock);
    p_scheduler_destroy();
}

static void simple_locker(void *lock_arg)
{
    PRWlock *lock = lock_arg;

    p_rwlock_lock_read(lock);
    p_rwlock_unlock(lock);
    p_rwlock_lock_write(lock);
    p_rwlock_unlock(lock);
}

static void test_rwlock_simple(void **state UNUSED)
{
    PRWlock lock;

    p_rwlock_init(&lock);

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, simple_locker, &lock, false);
    p_scheduler_run();

    p_rwlock_destroy(&lock);
    p_scheduler_destroy();
}

static void sem_nonblocking(void *sem_arg)
{
    PSem *sem = sem_arg;

    assert_true(p_sem_trydec(sem, 2));
    assert_false(p_sem_trydec(sem, 1));
    p_sem_inc(sem, 2);
    assert_true(p_sem_trydec(sem, 2));
    assert_false(p_sem_trydec(sem, 1));
    p_sem_inc(sem, 2);
}

static void test_sem_nonblocking(void **state UNUSED)
{
    PSem sem;

    p_sem_init(&sem, 2);

    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, sem_nonblocking, &sem, false);
    p_scheduler_run();

    p_sem_destroy(&sem);
    p_scheduler_destroy();
}

static int sem_step = 0;
static int sem_flag = false;

static void incrementer(void *sem_arg)
{
    PSem *sem = sem_arg;
    assert_int_equal(sem_step++, 4);
    p_sem_inc(sem, 2);
    LOOP(100, i)
        p_fiber_yield();
    sem_flag = true;
    p_sem_inc(sem, 2);
}

static void decrementer(void *sem_arg)
{
    PSem *sem = sem_arg;
    assert_in_range(sem_step++, 0, 3);
    p_sem_dec(sem, 1);
    if (sem_flag)
        assert_in_range(sem_step++, 7, 8);
    else
        assert_in_range(sem_step++, 5, 6);
}

static void test_sem_blocking(void **state UNUSED)
{
    PSem sem;

    p_sem_init(&sem, 0);

    p_scheduler_init(&scheduler_config);

    LOOP(4, i)
        p_fiber_init(FG_A, decrementer, &sem, false);
    p_fiber_init(FG_A, incrementer, &sem, false);

    p_scheduler_run();

    p_sem_destroy(&sem);
    p_scheduler_destroy();
}

static int event_step = 0;

static void event_one_waiter(void *event_arg)
{
    PEvent *event = event_arg;

    assert_in_range(event_step++, 0, 3);
    p_event_wait(event);
    assert_int_equal((event_step++) % 2, 1);
}

static void event_one_setter(void *event_arg)
{
    PEvent *event = event_arg;

    LOOP(4, i) {
        p_event_release_one(event);
        assert_int_equal((event_step++) % 2, 0);
        p_fiber_yield();
    }
}

static void test_event_one(void **state UNUSED)
{
    PEvent event;

    p_event_init(&event);

    p_scheduler_init(&scheduler_config);

    LOOP(4, i)
        p_fiber_init(FG_A, event_one_waiter, &event, false);
    p_fiber_init(FG_A, event_one_setter, &event, false);

    p_scheduler_run();

    p_event_destroy(&event);
    p_scheduler_destroy();
}

static void event_all_waiter(void *event_arg)
{
    PEvent *event = event_arg;

    p_event_wait(event);
}

static void event_all_setter(void *event_arg)
{
    PEvent *event = event_arg;

    p_event_release_all(event);
}

static void test_event_all(void **state UNUSED)
{
    PEvent event;

    p_event_init(&event);

    p_scheduler_init(&scheduler_config);

    LOOP(4, i)
        p_fiber_init(FG_A, event_all_waiter, &event, false);
    p_fiber_init(FG_A, event_all_setter, &event, false);

    p_scheduler_run();

    p_event_destroy(&event);
    p_scheduler_destroy();
}

static void iter(void *arg) {
    size_t *count = arg;
    LOOP(*count, i)
        p_fiber_yield();
}

static void test_perf(void **state UNUSED)
{
    size_t iters = 100000;
    size_t num_fibers = 10;

    p_scheduler_init(&scheduler_config);
    LOOP(num_fibers, i)
        p_fiber_init(FG_A, iter, &iters, false);

    uint64_t start = p_get_clock_time_nano();
    p_scheduler_run();
    uint64_t end = p_get_clock_time_nano();
    float avg = (float) (end - start) / (iters * num_fibers);
    printf("Iterations: %lu. Average: %.3fns. Total: %lu\n", iters, avg, end - start);
    assert_in_range(avg, 100, 500);

    p_scheduler_destroy();
}

static void inner()
{
    p_show_backtrace();
}

static void outer(void *arg)
{
    (void) arg;

    inner();
}

static void test_backtrace(void **state UNUSED)
{
    p_scheduler_init(&scheduler_config);
    p_fiber_init(FG_A, outer, NULL, false);
    p_scheduler_run();
    p_scheduler_destroy();
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_yield),
        cmocka_unit_test(test_join_single),
        cmocka_unit_test(test_join_all),
        cmocka_unit_test(test_sleep),
        cmocka_unit_test(test_fast_sleep),
        cmocka_unit_test(test_qlock),
        cmocka_unit_test(test_rwlock_barrier),
        cmocka_unit_test(test_rwlock_simple),
        cmocka_unit_test(test_sem_nonblocking),
        cmocka_unit_test(test_sem_blocking),
        cmocka_unit_test(test_event_one),
        cmocka_unit_test(test_event_all),
        cmocka_unit_test(test_perf),
        cmocka_unit_test(test_backtrace)
    };
    return cmocka_run_group_tests(tests, NULL, NULL);
}
