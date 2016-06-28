/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "vmsg_test.hpp"

TEST(TestVMsg, test)
{
    VMsgTest test;
    test.init();
    test.run_test();
    test.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}


