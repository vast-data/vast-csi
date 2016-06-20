/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "plasma/memory/pool.hpp"
#include "plasma/data/hash.hpp"
#include "plasma/utils/types.hpp"

typedef struct person person;
struct person {
    char name[64];
};

using P::Index;
using P::Hash;
using P::Pool;

static bool match_person(void *match_arg, Index index, void *key, size_t length)
{
    Pool *pool = (Pool *)match_arg;
    person *p = (person *)pool->index_to_address(index);
    return memcmp(key, p->name, length) == 0;
}

TEST(TestHash, test_set) {
    Pool pool;
    pool.init(4, sizeof(person));
    Hash hash;
    hash.init(1, 4, match_person, &pool);

    Index p1i = pool.alloc();
    Index p2i = pool.alloc();
    Index p3i = pool.alloc();
    person *p1 = (person *) pool.index_to_address(p1i);
    person *p2 = (person *) pool.index_to_address(p2i);
    person *p3 = (person *) pool.index_to_address(p3i);
    strcpy(p1->name, "foo");
    strcpy(p2->name, "bar");
    strcpy(p3->name, "bar");

    ASSERT_TRUE(hash.set(p1->name, 3, p1i));
    ASSERT_TRUE(hash.set(p2->name, 3, p2i));
    // existing key with same value
    ASSERT_FALSE(hash.set(p2->name, 3, p2i));
    // existing key with new value
    ASSERT_TRUE(hash.set(p3->name, 3, p3i));

    ASSERT_EQ(hash.get((void *)"bar", 3), p3i);
    ASSERT_EQ(hash.get((void *)"foo", 3), p1i);

    hash.destroy();
    pool.destroy();
}

TEST(TestHash, test_remove)
{
    Pool pool;
    pool.init(2, sizeof(person));
    Hash hash;
    hash.init(1, 2, match_person, &pool);

    Index p1i = pool.alloc();
    Index p2i = pool.alloc();
    person *p1 = (person *) pool.index_to_address(p1i);
    person *p2 = (person *) pool.index_to_address(p2i);

    strcpy(p1->name, "foo");
    strcpy(p2->name, "bar");
    hash.set(p1->name, 3, p1i);
    hash.set(p2->name, 3, p2i);

    ASSERT_TRUE(hash.remove(p1->name, 3));
    ASSERT_EQ(hash.get((void *)"foo", 3), P::INVALID_INDEX);
    ASSERT_FALSE(hash.remove(p1->name, 3));
    ASSERT_TRUE(hash.remove(p2->name, 3));
    ASSERT_EQ(hash.get((void *)"bar", 3), P::INVALID_INDEX);
    ASSERT_FALSE(hash.remove(p2->name, 3));

    hash.destroy();
    pool.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
