/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>

#include "plasma/execution/env.hpp"
#include "plasma/utils/assert.hpp"
#include "test_module.hpp"

TEST(TestEnv, test)
{
    P::Env::get()->run("tests/env_test.config");
    ASSERT_MSG(TestModule::is_init(), "test module expected to be init");
    ASSERT_MSG(TestModule::is_started(), "test module expected to be started");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
