/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "globals.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/utils/os.hpp"
#include "test_module.hpp"

using namespace P;

static void create_system_guid()
{
    GUID guid = GUID::create();
    char guid_string[GUID::STRING_SIZE];
    guid.to_string(guid_string);
    ASSERT_TRUE(string_to_file("data/system.guid", guid_string));
}

static void init_func(P::Silo *silo, void *ctx)
{

}

static void start_func(void *ctx)
{
    env_stop = true;
}

TEST(TestEnv, sanity)
{
    create_system_guid();
    TestModule::set_init_func(init_func, nullptr);
    TestModule::set_start_func(start_func, nullptr);

    P::Env::get()->run("dist/env" /* binary_path */, "tests/cluster_test.config");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
