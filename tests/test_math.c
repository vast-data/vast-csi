/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <cmocka.h>

#include "math.h"

static void test_positive(void **state)
{
    (void) state;

    assert_int_equal(add(2, 1), 3);
}

static void test_negative(void **state)
{
    (void) state;

    assert_int_equal(add(2, -5), -3);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_positive),
        cmocka_unit_test(test_negative),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
