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
static p_fiber_group_config fiber_groups[] = {
    {.fiber_count = 40, .stack_size = PAGE_SIZE * 16},
    {.fiber_count = 30, .stack_size = PAGE_SIZE * 8},
    {.fiber_count = 20, .stack_size = PAGE_SIZE * 8}
};
static p_scheduler_config scheduler_config = {
    .fiber_groups = fiber_groups, .group_count = NUM_ELEMENTS(fiber_groups)
};

static void test_yield(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, increment, &value);
    p_fiber_init(1, increment, &value);
    p_fiber_init(1, increment, &value);
    p_fiber_init(2, increment, &value);
    p_scheduler_run();
    p_scheduler_destroy();

    assert_int_equal(value, 12);
}

static void increment_twice_serial(void *value)
{
    int *num_ptr = value;
    p_fiber *f1, *f2;
    f1 = p_fiber_init(0, increment, value);
    p_join(f1);

    f2 = p_fiber_init(0, increment, value);
    p_join(f2);
    assert_int_equal(*num_ptr, 6);
}

static void test_join_single(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, increment_twice_serial, &value);
    p_scheduler_run();
    p_scheduler_destroy();

    assert_int_equal(value, 6);
}

static void increment_twice_parallel(void *value)
{
    int *num_ptr = value;
    p_fiber *f1, *f2;
    f1 = p_fiber_init(0, increment, value);
    f2 = p_fiber_init(0, increment, value);

    p_join_init();
    p_join_add(f1);
    p_join_add(f2);
    p_join_all();
    assert_int_equal(*num_ptr, 6);
    (*num_ptr)++;
}

static void test_join_all(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, increment_twice_parallel, &value);
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

static void test_sleep(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, first_sleeper, &value);
    p_fiber_init(0, second_sleeper, &value);

    p_scheduler_run();
    assert_int_equal(value, 3);

    p_scheduler_destroy();
}

static void fast_sleeper(void *arg)
{
    int *value = arg;

    assert_in_range(p_fast_sleep(1000), 1000, 1200);

    *value = 1;
}

static void test_fast_sleep(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, fast_sleeper, &value);

    p_scheduler_run();
    assert_int_equal(value, 1);

    p_scheduler_destroy();
}

static void iter(void *arg) {
    size_t *count = arg;
    LOOP(*count, i)
        p_fiber_yield();
}

static void test_perf(void **state)
{
    (void) state;

    size_t iters = 100000;
    size_t num_fibers = 10;

    p_scheduler_init(&scheduler_config);
    LOOP(num_fibers, i)
        p_fiber_init(0, iter, &iters);

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

static void test_backtrace(void **state)
{
    (void) state;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, outer, NULL);
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
        cmocka_unit_test(test_perf),
        cmocka_unit_test(test_backtrace)
    };
    return cmocka_run_group_tests(tests, NULL, NULL);
}
