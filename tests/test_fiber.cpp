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

// Helper function, allocating a buffer on the stack according to the given value.
static void alloc_on_stack(void *value)
{
    int alloc_size = *(int*)value;
    unsigned char buf[alloc_size];
    memset(buf, 0xFF, alloc_size);
    // Make sure memset will work in non-debug mode (i.e. not optimized out by the compiler):
    *((int*)value) = buf[0] + buf[alloc_size - 1];

    Fiber::yield();
}

// Helper function, testing stack allocation.
// Using FG_D (stack size is 4 pages).
// In debug mode, we catch the stack overflow using the page guard (mprotect'ing it causes a segfault when trying to
// write to the protected page. In release mode, there's no page guard so this is caught when checking for the magic (in
// context_switch).
static void test_stack_alloc(bool should_overflow)
{
    int alloc_size = should_overflow ? 4 * 4096 : 3 * 4096;

    Scheduler::init(&scheduler_config);
    Fiber *fiber = Fiber::init(FG_D, alloc_on_stack, &alloc_size, false);

    if (should_overflow) {
#ifdef DEBUG
        // Expect a segfault due to mprotect'ing a page guard:
        ASSERT_DEATH(Scheduler::run(), "");
#else
        // Expect a panic due to STACK_OVERFLOW_MAGIC:
        ASSERT_DEATH(Scheduler::run(), "PANIC: assertion failed: .*STACK_OVERFLOW_MAGIC");
#endif
        // Explicitly destroy the fiber (which is still running), otherwise we won't be able to destroy the scheduler:
        fiber->destroy();
    } else {
        Scheduler::run();
    }
    Scheduler::destroy();
}
TEST(TestFiber, test_stack_no_overflow)
{
    test_stack_alloc(false);
}

TEST(TestFiber, test_stack_overflow)
{
    test_stack_alloc(true);
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
