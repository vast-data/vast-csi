/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

static void test_insert(void **state)
{
    (void) state;

    p_dlist *list = p_dlist_init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;
    assert_true(p_dlist_is_empty(list, anchor));

    p_dlist_insert(list, &anchor, 1);
    assert_false(p_dlist_is_empty(list, anchor));

    p_dlist_insert(list, &anchor, 2);
    assert_int_equal(anchor, 2);

    p_dlist_destroy(list);
}

static void test_add_after(void **state)
{
    (void) state;

    p_dlist *list = p_dlist_init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist_insert(list, &anchor, 0);
    p_dlist_add_after(list, &anchor, 0, 2);
    p_dlist_add_after(list, &anchor, 0, 1);
    assert_int_equal(anchor, 0);
    assert_int_equal(p_dlist_next(list, &anchor, 0), 1);
    assert_int_equal(p_dlist_next(list, &anchor, 1), 2);
    assert_int_equal(p_dlist_next(list, &anchor, 2), 0);

    p_dlist_destroy(list);
}

static void test_add_before(void **state)
{
    (void) state;

    p_dlist *list = p_dlist_init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist_insert(list, &anchor, 0);
    p_dlist_add_before(list, &anchor, 0, 2);
    p_dlist_add_before(list, &anchor, 0, 1);
    assert_int_equal(anchor, 0);
    assert_int_equal(p_dlist_next(list, &anchor, 2), 1);
    assert_int_equal(p_dlist_next(list, &anchor, 1), 0);
    assert_int_equal(p_dlist_next(list, &anchor, 0), 2);

    p_dlist_destroy(list);
}

static void test_remove(void **state)
{
    (void) state;

    p_dlist *list = p_dlist_init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist_insert(list, &anchor, 0);
    p_dlist_add_after(list, &anchor, 0, 1);
    p_dlist_add_after(list, &anchor, 1, 2);

    p_dlist_remove(list, &anchor, 1);
    assert_int_equal(anchor, 0);
    assert_int_equal(p_dlist_next(list, &anchor, 0), 2);

    p_dlist_remove(list, &anchor, 0);
    assert_int_equal(anchor, 2);

    p_dlist_remove(list, &anchor, 2);
    assert_true(p_dlist_is_empty(list, anchor));

    p_dlist_destroy(list);
}

static void test_each(void **state)
{
    (void) state;


    p_dlist *list = p_dlist_init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_index i;
    P_DLIST_EACH(list, anchor, i) {}

    p_dlist_insert(list, &anchor, 0);
    p_dlist_add_after(list, &anchor, 0, 1);
    p_dlist_add_after(list, &anchor, 1, 2);

    p_index j = 0;
    P_DLIST_EACH(list, anchor, i) {
        assert_int_equal(i, j++);
    }
    assert_int_equal(j, 3);
}

static void test_queue(void **state)
{
    (void) state;


    p_dlist *list = p_dlist_init(2);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist_append(list, &anchor, 0);
    p_dlist_append(list, &anchor, 1);

    assert_int_equal(p_dlist_pop(list, &anchor), 0);
    assert_int_equal(p_dlist_pop(list, &anchor), 1);
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
