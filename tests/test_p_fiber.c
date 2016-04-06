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

static p_fiber_group_config fiber_groups[] = {
    {.fiber_count = 40, .stack_size = 8092},
    {.fiber_count = 30, .stack_size = 4096},
    {.fiber_count = 20, .stack_size = 4096}
};
static p_scheduler_config scheduler_config = {.fiber_groups = fiber_groups, .group_count = NUM_ELEMENTS(fiber_groups)};

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

    assert_int_equal(value, 12);
}

static void increment_twice_serial(void *value)
{
    int *num_ptr = value;
    p_fiber *f1, *f2;
    f1 = p_fiber_init(0, increment, value);
    f2 = p_fiber_init(0, increment, value);

    p_join(f1);
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
}

static void test_join_all(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init(&scheduler_config);
    p_fiber_init(0, increment_twice_parallel, &value);
    p_scheduler_run();

    assert_int_equal(value, 6);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_yield),
        cmocka_unit_test(test_join_single),
        cmocka_unit_test(test_join_all)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
