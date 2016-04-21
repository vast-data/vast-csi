/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

int murmur_test(void);

static void test_murmur(void **state)
{
    (void) state;

    assert_false(murmur_test());
}

typedef struct person person;
struct person {
    char name[64];
};

static bool match_person(void *match_arg, PIndex index, void *key, size_t length)
{
    PPool *pool = match_arg;
    person *p = p_pool_index_to_address(pool, index);
    return memcmp(key, p->name, length) == 0;
}

static void test_set(void **state)
{
    (void) state;

    PPool *pool = p_pool_init(4, sizeof(person));
    PHash *hash = p_hash_init(1, 4, match_person, pool);

    PIndex p1i = p_pool_alloc(pool);
    PIndex p2i = p_pool_alloc(pool);
    PIndex p3i = p_pool_alloc(pool);
    person *p1 = p_pool_index_to_address(pool, p1i);
    person *p2 = p_pool_index_to_address(pool, p2i);
    person *p3 = p_pool_index_to_address(pool, p3i);
    strcpy(p1->name, "foo");
    strcpy(p2->name, "bar");
    strcpy(p3->name, "bar");

    assert_true(p_hash_set(hash, p1->name, 3, p1i));
    assert_true(p_hash_set(hash, p2->name, 3, p2i));
    // existing key with same value
    assert_false(p_hash_set(hash, p2->name, 3, p2i));
    // existing key with new value
    assert_true(p_hash_set(hash, p3->name, 3, p3i));

    assert_int_equal(p_hash_get(hash, "bar", 3), p3i);
    assert_int_equal(p_hash_get(hash, "foo", 3), p1i);

    p_hash_destroy(hash);
    p_pool_destroy(pool);
}

static void test_remove(void **state)
{
    (void) state;

    PPool *pool = p_pool_init(2, sizeof(person));
    PHash *hash = p_hash_init(1, 2, match_person, pool);

    PIndex p1i = p_pool_alloc(pool);
    PIndex p2i = p_pool_alloc(pool);
    person *p1 = p_pool_index_to_address(pool, p1i);
    person *p2 = p_pool_index_to_address(pool, p2i);

    strcpy(p1->name, "foo");
    strcpy(p2->name, "bar");
    p_hash_set(hash, p1->name, 3, p1i);
    p_hash_set(hash, p2->name, 3, p2i);

    assert_true(p_hash_remove(hash, p1->name, 3));
    assert_int_equal(p_hash_get(hash, "foo", 3), P_INVALID_INDEX);
    assert_false(p_hash_remove(hash, p1->name, 3));
    assert_true(p_hash_remove(hash, p2->name, 3));
    assert_int_equal(p_hash_get(hash, "bar", 3), P_INVALID_INDEX);
    assert_false(p_hash_remove(hash, p2->name, 3));

    p_hash_destroy(hash);
    p_pool_destroy(pool);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_murmur),
        cmocka_unit_test(test_set),
        cmocka_unit_test(test_remove),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
