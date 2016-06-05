#include <gtest/gtest.h>

#include "plasma/utils/assert.hpp"

namespace {

TEST(TestAsserts, test_panic) {
    ASSERT_DEATH(PANIC("Drop the mic"), "PANIC: Drop the mic");
}

TEST(TestAsserts, test_panic_location) {
    ASSERT_DEATH(PANIC("Drop the mic"), "at file: build/tests/test_assert.cpp line: 12");
}

TEST(TestAsserts, test_assert_panics) {
    int var = 1;
    ASSERT_DEATH(ASSERT(var > 2, "var isn't larger than 2"), "assertion failed: var isn't larger than 2 \\(var > 2\\)");
}

TEST(TestAsserts, test_assert) {
    int var = 1;
    ASSERT(var < 2, "var isn't smaller than 2");
}

TEST(TestAsserts, test_assert_op_panics) {
    int var = 1;
    ASSERT_DEATH(ASSERT_OP(var, >, 2, "var isn't larger than 2"), "assertion failed: var isn't larger than 2 \\(1 > 2\\)");
}

TEST(TestAsserts, test_assert_op_passes) {
    int var = 1;
    ASSERT_OP(var, <, 2, "var isn't smaller than 2");
}

}

int main(int argc, char **argv) {
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
