/* Copyright (C) Vast Data Ltd. */

#include "plasma/data/queue.hpp"
#include <gtest/gtest.h>

using P::Queue;

struct Bubu {
    uint32_t bla;
};

TEST(TestQueue, test) {
    Queue<Bubu> q;
    q.init(2);

    Bubu *b = q.alloc();
    b->bla = 1;
    q.push(b);

    b = q.alloc();
    b->bla = 2;
    q.push(b);
    ASSERT_EQ(q.alloc(), nullptr);

    b = q.pop();
    ASSERT_EQ(b->bla, 1);
    q.free(b);
    b = q.pop();
    ASSERT_EQ(b->bla, 2);
    q.free(b);

    q.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
