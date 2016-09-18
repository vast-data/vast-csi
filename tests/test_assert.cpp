#include <gtest/gtest.h>

#include "plasma/utils/assert.hpp"

namespace {

void NO_RETURN test_panic()
{
    PANIC("Drop the mic");
}

TEST(TestAsserts, test_panic)
{
    ASSERT_DEATH(test_panic(), "PANIC: Drop the mic");
}

TEST(TestAsserts, test_panic_location)
{
    ASSERT_DEATH(test_panic(), "tests/test_assert.cpp line: 9");
}

void test_assert_panics()
{
    int var = 1;
    ASSERT(var > 2, "var isn't larger than 2");
}

TEST(TestAsserts, test_assert_panics)
{
    ASSERT_DEATH(test_assert_panics(), "assertion failed: \\(var > 2\\) var isn't larger than 2");
}

TEST(TestAsserts, test_assert)
{
    int var = 1;
    ASSERT(var < 2, "var isn't smaller than 2");
}

void test_assert_op_panics()
{
    int var = 1;
    ASSERT_OP(var, >, 2, "var isn't larger than 2");
}

TEST(TestAsserts, test_assert_op_panics)
{
    ASSERT_DEATH(test_assert_op_panics(), "assertion failed: \\(var > 2\\) \\(1 > 2\\) var isn't larger than 2");
}

void assert_not_null()
{
    void *p1 = nullptr;
    ASSERT_NOT_NULL(p1)
}

TEST(TestAsserts, test_assert_not_null)
{
    ASSERT_DEATH(assert_not_null(), "p1 != nullptr");
}

TEST(TestAsserts, test_assert_op_passes)
{
    int var = 1;
    ASSERT_OP(var, <, 2, "var isn't smaller than 2");
}

}

int main(int argc, char **argv) {
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
