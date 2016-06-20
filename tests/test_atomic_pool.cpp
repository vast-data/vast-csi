/* Copyright (C) Vast Data Ltd. */

#include "plasma/memory/atomic_pool.hpp"
#include <gtest/gtest.h>
#include "test_common_scheduler.hpp"

using P::AtomicPool;

static uint test_counter =0;
static const uint element_count = 3;
struct APoolTestArg {
    AtomicPool<int> *pool;
    int *object;
};

static void objects_multi_allocator(void *arg)
{
    AtomicPool<int> *pool = (AtomicPool<int>*)arg;
    int *arr[element_count];
    test_counter++;
    pool->alloc_multiple(arr, element_count);
    test_counter++;
    pool->free_multiple(arr, element_count);
}

static void objects_releaser(void *arg)
{
    APoolTestArg *test_arg = (APoolTestArg*)arg;
    test_counter++;
    test_arg->pool->free(test_arg->object);
}

static void test_multiple(void *arg UNUSED)
{
    AtomicPool<int> pool;
    pool.init(element_count);

    int *first_arr[element_count];
    APoolTestArg arg_arr[element_count];

    LOOP(element_count, i) {
        first_arr[i] = pool.alloc();
        ASSERT_TRUE(first_arr[i] != nullptr);
    }

    LOOP(element_count, i) {
        arg_arr[i].object = first_arr[i];
        arg_arr[i].pool = &pool;
        P::Fiber::init(FG_B, objects_releaser, &arg_arr[i], false);
    }

    int *second_arr[element_count];
    pool.alloc_multiple(second_arr, element_count);
    EXPECT_EQ(element_count, test_counter);

    P::Fiber::init(FG_B, objects_multi_allocator, &pool, true);

    P::Fiber::yield();
    EXPECT_EQ(element_count + 1, test_counter);

    pool.free_multiple(second_arr, element_count);

    P::Fiber::join_all();
    EXPECT_EQ(element_count + 2, test_counter);

    pool.destroy();
}

TEST(TestAtomicPool, test_multiple)
{
    P::Scheduler::init(&scheduler_config);
    P::Fiber::init(FG_A, test_multiple, nullptr, false);
    P::Scheduler::run();
    P::Scheduler::destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
