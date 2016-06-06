/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

static void test_insert(void **state UNUSED)
{
    PDListPool *listpool = p_dlistpool_init(3);
    PDListAnchor anchor;
    p_dlistanchor_init(&anchor);
    PDList list;
    p_dlist_init(&list, &anchor, listpool);

    assert_true(p_dlist_is_empty(&list));

    p_dlist_insert(&list, 1);
    assert_false(p_dlist_is_empty(&list));

    p_dlist_insert(&list, 2);
    assert_int_equal(p_dlist_get_first(&list), 2);

    p_dlistpool_destroy(listpool);
}

static void test_add_after(void **state UNUSED)
{
    PDListPool *listpool = p_dlistpool_init(3);
    PDListAnchor anchor;
    p_dlistanchor_init(&anchor);
    PDList list;
    p_dlist_init(&list, &anchor, listpool);

    p_dlist_insert(&list, 0);
    p_dlist_add_after(&list, 0, 2);
    p_dlist_add_after(&list, 0, 1);
    assert_int_equal(p_dlist_get_first(&list), 0);
    assert_int_equal(p_dlist_next(&list, 0), 1);
    assert_int_equal(p_dlist_next(&list, 1), 2);
    assert_int_equal(p_dlist_next(&list, 2), 0);

    p_dlistpool_destroy(listpool);
}

static void test_add_before(void **state UNUSED)
{
    PDListPool *listpool = p_dlistpool_init(3);
    PDListAnchor anchor;
    p_dlistanchor_init(&anchor);
    PDList list;
    p_dlist_init(&list, &anchor, listpool);

    p_dlist_insert(&list, 0);
    p_dlist_add_before(&list, 0, 2);
    p_dlist_add_before(&list, 0, 1);
    assert_int_equal(p_dlist_get_first(&list), 2);
    assert_int_equal(p_dlist_next(&list, 2), 1);
    assert_int_equal(p_dlist_next(&list, 1), 0);
    assert_int_equal(p_dlist_next(&list, 0), 2);

    p_dlistpool_destroy(listpool);
}

static void test_remove(void **state UNUSED)
{
    PDListPool *listpool = p_dlistpool_init(3);
    PDListAnchor anchor;
    p_dlistanchor_init(&anchor);
    PDList list;
    p_dlist_init(&list, &anchor, listpool);

    p_dlist_insert(&list, 0);
    p_dlist_add_after(&list, 0, 1);
    p_dlist_add_after(&list, 1, 2);

    p_dlist_remove(&list, 1);
    assert_int_equal(p_dlist_get_first(&list), 0);
    assert_int_equal(p_dlist_next(&list, 0), 2);

    p_dlist_remove(&list, 0);
    assert_int_equal(p_dlist_get_first(&list), 2);

    p_dlist_remove(&list, 2);
    assert_true(p_dlist_is_empty(&list));

    p_dlistpool_destroy(listpool);
}

static void test_each(void **state UNUSED)
{
    PDListPool *listpool = p_dlistpool_init(3);
    PDListAnchor anchor;
    p_dlistanchor_init(&anchor);
    PDList list;
    p_dlist_init(&list, &anchor, listpool);

    P_DLIST_EACH(&list,  i) {}

    p_dlist_insert(&list, 0);
    p_dlist_add_after(&list, 0, 1);
    p_dlist_add_after(&list, 1, 2);

    PIndex j = 0;
    P_DLIST_EACH(list, i) {
        assert_int_equal(i, j++);
    }
    assert_int_equal(j, 3);

    p_dlistpool_destroy(listpool);
}

static void test_queue(void **state UNUSED)
{
    PDListPool *listpool = p_dlistpool_init(2);
    PDListAnchor anchor;
    p_dlistanchor_init(&anchor);
    PDList list;
    p_dlist_init(&list, &anchor, listpool);

    p_dlist_append(&list, 0);
    p_dlist_append(&list, 1);

    assert_int_equal(p_dlist_pop(&list), 0);
    assert_int_equal(p_dlist_pop(&list), 1);

    p_dlistpool_destroy(listpool);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_insert),
        cmocka_unit_test(test_add_after),
        cmocka_unit_test(test_add_before),
        cmocka_unit_test(test_remove),
        cmocka_unit_test(test_each),
        cmocka_unit_test(test_queue)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
