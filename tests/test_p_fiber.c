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

static void test(void **state)
{
    (void) state;

    int value = 0;

    p_fiber_group_config fiber_groups[] = {
        {.fiber_count = 40, .stack_size = 8092},
        {.fiber_count = 30, .stack_size = 4096},
        {.fiber_count = 20, .stack_size = 4096}
    };
    p_scheduler_config config = {.fiber_groups = fiber_groups, .group_count = NUM_ELEMENTS(fiber_groups)};
    p_scheduler_init(&config);
    p_fiber_init(0, increment, &value);
    p_fiber_init(1, increment, &value);
    p_fiber_init(1, increment, &value);
    p_fiber_init(2, increment, &value);
    p_fiber_init(2, increment, &value);
    p_scheduler_run();

    assert_int_equal(value, 15);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
