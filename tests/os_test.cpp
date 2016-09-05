/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>

#include "plasma/utils/os.hpp"

TEST(OS, string_to_file_failure)
{
    EXPECT_FALSE(P::string_to_file("no/such/path/test.txt", "123"));
}

TEST(OS, string_to_file_to_string)
{
    P::ensure_directory_exists("data/os_test");
    const char str[] = "123\n456\n789.";
    EXPECT_TRUE(P::string_to_file("data/os_test/test.txt", str));

    // buf size too small
    char buf[100];
    EXPECT_FALSE(P::file_to_string("data/os_test/test.txt", 10, buf));

    EXPECT_TRUE(P::file_to_string("data/os_test/test.txt", 100, buf));
    EXPECT_STREQ(str, buf);
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
