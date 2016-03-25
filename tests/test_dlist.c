/* Copyright (C) Vast Data, Inc - All Rights Reserved
 * Unauthorized copying of this file, via any medium is strictly
 * prohibited proprietary and confidential.
 */
#include <stdlib.h>
#include <stdio.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

#include "plasma/dlist.h"

static void test_insert(void **state)
{
    (void) state;

    p_dlist *list = p_dlist__init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;
    assert_true(p_dlist__is_empty(list, anchor));

    p_dlist__insert(list, &anchor, 1);
    assert_false(p_dlist__is_empty(list, anchor));

    p_dlist__insert(list, &anchor, 2);
    assert_int_equal(anchor, 2);

    p_dlist__destroy(list);
}

static void test_next_prev(void **state)
{
    (void) state;

    p_dlist *list = p_dlist__init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;
    assert_true(p_dlist__is_empty(list, anchor));

    p_dlist__insert(list, &anchor, 1);
    assert_false(p_dlist__is_empty(list, anchor));

    p_dlist__destroy(list);
}

static void test_add_after(void **state)
{
    (void) state;

    p_dlist *list = p_dlist__init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist__insert(list, &anchor, 0);
    p_dlist__add_after(list, &anchor, 0, 2);
    p_dlist__add_after(list, &anchor, 0, 1);
    assert_int_equal(anchor, 0);
    assert_int_equal(p_dlist__next(list, &anchor, 0), 1);
    assert_int_equal(p_dlist__next(list, &anchor, 1), 2);
    assert_int_equal(p_dlist__next(list, &anchor, 2), 0);

    p_dlist__destroy(list);
}

static void test_add_before(void **state)
{
    (void) state;

    p_dlist *list = p_dlist__init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist__insert(list, &anchor, 0);
    p_dlist__add_before(list, &anchor, 0, 2);
    p_dlist__add_before(list, &anchor, 0, 1);
    assert_int_equal(anchor, 0);
    assert_int_equal(p_dlist__next(list, &anchor, 2), 1);
    assert_int_equal(p_dlist__next(list, &anchor, 1), 0);
    assert_int_equal(p_dlist__next(list, &anchor, 0), 2);

    p_dlist__destroy(list);
}

static void test_remove(void **state)
{
    (void) state;


    p_dlist *list = p_dlist__init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist__insert(list, &anchor, 0);
    p_dlist__add_after(list, &anchor, 0, 1);
    p_dlist__add_after(list, &anchor, 1, 2);

    p_dlist__remove(list, &anchor, 1);
    assert_int_equal(anchor, 0);
    assert_int_equal(p_dlist__next(list, &anchor, 0), 2);

    p_dlist__remove(list, &anchor, 0);
    assert_int_equal(anchor, 2);

    p_dlist__remove(list, &anchor, 2);
    assert_true(p_dlist__is_empty(list, anchor));

    p_dlist__destroy(list);
}

static void test_each(void **state)
{
    (void) state;


    p_dlist *list = p_dlist__init(3);
    p_dlist_anchor anchor = P_DLIST_ANCHOR_INIT;

    p_dlist__insert(list, &anchor, 0);
    p_dlist__add_after(list, &anchor, 0, 1);
    p_dlist__add_after(list, &anchor, 1, 2);

    p_index j = 0;
    p_dlist_anchor i;
    P_DLIST__EACH(list, anchor, i) {
        assert_int_equal(i, j++);
    }
    assert_int_equal(j, 3);

}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_insert),
        cmocka_unit_test(test_next_prev),
        cmocka_unit_test(test_add_after),
        cmocka_unit_test(test_add_before),
        cmocka_unit_test(test_remove),
        cmocka_unit_test(test_each)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
