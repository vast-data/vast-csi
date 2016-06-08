/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "plasma/utils/time.hpp"

TEST(TestSleep, test_get_time_nano)
{
    uint64_t start = P::get_clock_time_nano();
    const uint64_t iters = 1000000;
    uint64_t value = 0;
    for (size_t i = 0; i < iters; i++) {
        value = P::get_time_nano();
    }

    uint64_t end = P::get_clock_time_nano();
    float avg = (float) (end - start) / iters;
    // takes 20ns on my mac. less than 10ns or more than 100ns would be suspicious.
    printf("Iterations: %lu. Average: %.3fns\n", iters, avg);

    ASSERT_GE(avg, 10);
    ASSERT_LE(avg, 100);
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
