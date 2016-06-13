/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "plasma/fiber/scheduler.hpp"
#include "plasma/fiber/sleep.hpp"
#include "plasma/utils/time.hpp"

#include "test_common_scheduler.hpp"

static void iter(void *arg)
{
    size_t *count = (size_t*)arg;
    LOOP(*count, i) {
        P::Fiber::yield();
    }
}

TEST(TestPerformance, test_context_switch)
{
    size_t iters = 100000;
    size_t num_fibers = 10;
    P::Scheduler::init(&scheduler_config);

    LOOP(num_fibers, i) {
        P::Fiber::init(FG_A, iter, &iters, false);
    }

    uint64_t start = P::get_clock_time_nano();
    P::Scheduler::run();
    uint64_t end = P::get_clock_time_nano();
    float avg = (float) (end - start) / (iters * num_fibers);
    printf("Iterations: %lu. Average: %.3fns. Total: %lu\n", iters, avg, end - start);

    ASSERT_GE(avg, 100);
    ASSERT_LE(avg, 500);

    P::Scheduler::destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
