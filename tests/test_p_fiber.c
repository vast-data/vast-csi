/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

static void increment(void *value)
{
    int *num_ptr = value;
    (*num_ptr)++;
    p_fiber_yield();
    (*num_ptr)++;
    p_fiber_yield();
    (*num_ptr)++;
}

static void test(void **state)
{
    (void) state;

    int value = 0;

    p_scheduler_init();
    p_fiber_init(increment, &value);
    p_fiber_init(increment, &value);
    p_fiber_init(increment, &value);
    p_fiber_init(increment, &value);
    p_fiber_init(increment, &value);
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
