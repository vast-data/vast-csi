/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>

#include "plasma/fiber/scheduler.hpp"
#include "plasma/fiber/sleep.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/utils/backtrace.hpp"

#include "test_common_scheduler.hpp"

using namespace P;

static void increment(void *value)
{
    int *num_ptr = (int*) value;
    LOOP(3, i) {
        (*num_ptr)++;
        Fiber::yield();
    }
}

TEST(TestFiber, test_yield)
{
    int value = 0;

    Scheduler::init(&scheduler_config);
    Fiber::init(FG_A, increment, &value, false);
    Fiber::init(FG_B, increment, &value, false);
    Fiber::init(FG_B, increment, &value, false);
    Fiber::init(FG_C, increment, &value, false);
    Scheduler::run();
    Scheduler::destroy();

    ASSERT_EQ(value, 12);
}

static void increment_twice_serial(void *value)
{
    int *num_ptr = (int*) value;
    Fiber::init(FG_A, increment, value, true);
    Fiber::join_all();
    Fiber::init(FG_A, increment, value, true);
    Fiber::join_all();

    ASSERT_EQ(*num_ptr, 6);
}

TEST(TestFiber, test_join_single)
{
    int value = 0;

    Scheduler::init(&scheduler_config);
    Fiber::init(FG_A, increment_twice_serial, &value, false);
    Scheduler::run();
    Scheduler::destroy();

    ASSERT_EQ(value, 6);
}

static void increment_twice_parallel(void *value)
{
    int *num_ptr = (int*) value;
    Fiber::init(FG_A, increment, value, true);
    Fiber::init(FG_A, increment, value, true);

    Fiber::join_all();
    ASSERT_EQ(*num_ptr, 6);
    (*num_ptr)++;
}

TEST(TestFiber, test_join_all)
{
    int value = 0;

    Scheduler::init(&scheduler_config);
    Fiber::init(FG_A, increment_twice_parallel, &value, false);
    Scheduler::run();
    Scheduler::destroy();

    ASSERT_EQ(value, 7);
}

static void first_sleeper(void *arg)
{
    int *value = (int*) arg;
    auto result = TimerQueues::sleep(SleepInterval::SLEEP_100_MILLI);
    ASSERT_TRUE(result >= 100000 && result < 120000);
    *value = 1;
    result = TimerQueues::sleep_multi(SleepInterval::SLEEP_100_MILLI, 2);
    ASSERT_TRUE(result >= 200000 && result < 240000);
    ASSERT_EQ(*value, 2);
    *value = 3;
}

static void second_sleeper(void *arg)
{
    int *value = (int*) arg;
    auto result = TimerQueues::sleep_multi(SleepInterval::SLEEP_100_MILLI, 2);
    ASSERT_TRUE(result >= 200000 && result < 240000);
    ASSERT_EQ(*value, 1);
    *value = 2;
}

static void worker(void *arg)
{
    int *value = (int*) arg;
    while (*value != 3) {
        Fiber::yield();
    }
}

TEST(TestSleep, test_sleep)
{
    int value = 0;

    Scheduler::init(&scheduler_config);
    Fiber::init(FG_A, first_sleeper, &value, false);
    Fiber::init(FG_B, second_sleeper, &value, false);
    Fiber::init(FG_C, worker, &value, false);

    Scheduler::run();
    ASSERT_EQ(value, 3);

    Scheduler::destroy();
}

static void fast_sleeper(void *arg)
{
    int *value = (int*) arg;
    auto result = TimerQueues::fast_sleep(1000);
    ASSERT_TRUE(result >= 1000 && result < 1500);

    *value = 1;
}

TEST(TestSleep, test_fast_sleep)
{
    int value = 0;

    Scheduler::init(&scheduler_config);
    Fiber::init(FG_A, fast_sleeper, &value, false);

    Scheduler::run();
    ASSERT_EQ(value, 1);

    Scheduler::destroy();
}

static void inner()
{
    P::Backtracer::show_backtrace();
}

static void outer(void *arg UNUSED)
{
    inner();
}

TEST(TestBacktrace, test_backtrace)
{
    Scheduler::init(&scheduler_config);
    Fiber::init(FG_A, outer, nullptr, false);
    Scheduler::run();
    Scheduler::destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
