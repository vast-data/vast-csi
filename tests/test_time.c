/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

static void test_get_time_nano(void **state)
{
    (void) state;

    uint64_t start = p_get_clock_time_nano();
    uint64_t value, end, iters = 1000000;
    for (size_t i = 0; i < iters; i++) {
        value = p_get_time_nano();
    }
    (void) value;
    end = p_get_clock_time_nano();
    float avg = (float) (end - start) / iters;
    // takes 20ns on my mac. less than 10ns or more than 100ns would be suspicious.
    printf("Iterations: %lu. Average: %.3fns\n", iters, avg);
    assert_in_range(avg, 10, 100);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_get_time_nano)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
