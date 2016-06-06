/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "plasma/sync/spin_lock.hpp"

TEST(TestPool, test_spin) {
    P::SpinLock lock;
    lock.init();
    LOOP(1000000, i) {
        lock.lock();
        lock.unlock();
    }
    lock.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
