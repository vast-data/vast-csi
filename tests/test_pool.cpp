/* Copyright (C) Vast Data Ltd. */

#include <plasma/memory/pool.hpp>
#include <gtest/gtest.h>

using P::Pool;

TEST(TestPool, test_out_of_memory) {
    Pool pool;
    pool.init(2, sizeof(int));
    int *a = (int *) pool.alloc_address();
    int *b = (int *) pool.alloc_address();
    P::Index index = pool.alloc();
    *a = 1;
    *b = 2;
    ASSERT_EQ(*a, 1);
    ASSERT_EQ(*b, 2);
    ASSERT_EQ(index, -1);
    pool.destroy();
}

TEST(TestPool, test_alloc_free) {
    Pool pool;
    pool.init(2, sizeof(int));

    P::Index index = pool.alloc();
    ASSERT_NE(index, -1);
    pool.free(index);

    index = pool.alloc();
    ASSERT_NE(index, -1);
    pool.free(index);

    index = pool.alloc();
    ASSERT_NE(index, -1);
    pool.free(index);

    pool.destroy();
}

TEST(TestPool, test_partitions) {

    P::Index partitions[] = {1, 1};
    Pool pool;
    pool.partitioned_init(sizeof(int), 2, partitions);
    P::Index a = pool.partitioned_alloc(0);
    ASSERT_NE(a, -1);
    P::Index b = pool.partitioned_alloc(1);
    ASSERT_NE(b, -1);
    P::Index c = pool.partitioned_alloc(0);
    ASSERT_EQ(c, -1);
    P::Index d = pool.partitioned_alloc(1);
    ASSERT_EQ(d, -1);

    pool.partitioned_free(b, 1);

    b = pool.partitioned_alloc(1);
    ASSERT_NE(b, -1);

    pool.destroy();
}

int main(int argc, char **argv) {
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
