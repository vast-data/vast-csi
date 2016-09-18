/* Copyright (C) Vast Data Ltd. */

#include "plasma/data/spsc_queue.hpp"
#include <gtest/gtest.h>
#include <thread>
#include "plasma/utils/macros.hpp"

using P::SPSCQueue;

struct TestElement {
    SPSCQueue::Node node;
    uint64_t val;
};

static TestElement test_elements[100000];
static uint64_t expected_sum = 0;

static void producer(SPSCQueue *q)
{
    LOOP(NUM_ELEMENTS(test_elements), i) {
        test_elements[i].val = i;
        expected_sum += test_elements[i].val;
        q->push(&(test_elements[i].node), i);
        sched_yield();
        sched_yield();
        sched_yield();
        sched_yield();
    }
}

#define GET_TEST_NODE(IDX) \
     (&(test_elements[IDX].node))

static void consumer(SPSCQueue *q)
{
    uint64_t sum = 0;
    int visited_elements = 0;
    while (visited_elements != NUM_ELEMENTS(test_elements)) {
        SPSC_QUEUE_ITER(q, GET_TEST_NODE, curr) {
            sum += test_elements[curr].val;
            ASSERT_EQ(visited_elements, test_elements[curr].val);
            visited_elements++;
        }
    }
    ASSERT_EQ(sum, expected_sum);
}

TEST(TestSPSCQueue, test) {
    SPSCQueue q;
    q.init();

    std::thread consumer_thread(std::bind(consumer, &q));
    std::thread producer_thread(std::bind(producer, &q));

    consumer_thread.join();
    producer_thread.join();

    q.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
