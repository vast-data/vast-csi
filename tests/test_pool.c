/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

#include "plasma/pool.h"

static void test_out_of_memory(void **state)
{
    (void) state;

    p_pool *pool = p_pool__init(2, sizeof(int));
    int *a = p_pool__alloc(pool);
    int *b = p_pool__alloc(pool);
    int *c = p_pool__alloc(pool);
    *a = 1;
    *b = 2;
    assert_int_equal(*a, 1);
    assert_int_equal(*b, 2);
    assert_null(c);
    p_pool__destroy(pool);
}

static void test_alloc_free(void **state)
{
    (void) state;

    p_pool *pool = p_pool__init(2, sizeof(int));

    int *a = p_pool__alloc(pool);
    assert_non_null(a);
    p_pool__free(pool, a);

    a = p_pool__alloc(pool);
    assert_non_null(a);
    p_pool__free(pool, a);

    a = p_pool__alloc(pool);
    assert_non_null(a);
    p_pool__free(pool, a);

    p_pool__destroy(pool);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_out_of_memory),
        cmocka_unit_test(test_alloc_free)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
