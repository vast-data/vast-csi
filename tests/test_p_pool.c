/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

static void test_out_of_memory(void **state)
{
    (void) state;

    PPool *pool = p_pool_init(2, sizeof(int));
    int *a = p_pool_alloc_address(pool);
    int *b = p_pool_alloc_address(pool);
    PIndex index = p_pool_alloc(pool);
    *a = 1;
    *b = 2;
    assert_int_equal(*a, 1);
    assert_int_equal(*b, 2);
    assert_int_equal(index, -1);
    p_pool_destroy(pool);
}

static void test_alloc_free(void **state)
{
    (void) state;

    PPool *pool = p_pool_init(2, sizeof(int));

    PIndex index = p_pool_alloc(pool);
    assert_int_not_equal(index, -1);
    p_pool_free(pool, index);

    index = p_pool_alloc(pool);
    assert_int_not_equal(index, -1);
    p_pool_free(pool, index);

    index = p_pool_alloc(pool);
    assert_int_not_equal(index, -1);
    p_pool_free(pool, index);

    p_pool_destroy(pool);
}

static void test_partitions(void **state)
{
    (void) state;

    PIndex partitions[] = {1, 1};
    PPool *pool = p_pool_partitioned_init(sizeof(int), 2, partitions);
    PIndex a = p_pool_partitioned_alloc(pool, 0);
    assert_int_not_equal(a, -1);
    PIndex b = p_pool_partitioned_alloc(pool, 1);
    assert_int_not_equal(b, -1);
    PIndex c = p_pool_partitioned_alloc(pool, 0);
    assert_int_equal(c, -1);
    PIndex d = p_pool_partitioned_alloc(pool, 1);
    assert_int_equal(d, -1);

    p_pool_partitioned_free(pool, b, 1);

    b = p_pool_partitioned_alloc(pool, 1);
    assert_int_not_equal(b, -1);

    p_pool_destroy(pool);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_out_of_memory),
        cmocka_unit_test(test_alloc_free),
        cmocka_unit_test(test_partitions),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
