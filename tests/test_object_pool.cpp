/* Copyright (C) Vast Data Ltd. */

#include "plasma/memory/object_pool.hpp"
#include <gtest/gtest.h>

using P::ObjectPool;

TEST(TestObjectPool, test_out_of_memory)
{
    ObjectPool<int> pool;
    pool.init(2);

    int *a = pool.alloc();
    int *b = pool.alloc();
    int *c = pool.alloc();

    ASSERT_TRUE(a != nullptr);
    ASSERT_TRUE(b != nullptr);
    ASSERT_EQ(c, nullptr);
    pool.destroy();
}

TEST(TestObjectPool, test_alloc_free)
{
    ObjectPool<int> pool;
    pool.init(2);

    int *a = pool.alloc();

    for (uint i = 0; i < 6; ++i) {
        int *b = pool.alloc();
        ASSERT_TRUE(a != nullptr);
        pool.free(b);
    }

    pool.free(a);

    pool.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
