/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "plasma/utils/macros.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/execution/config_internal.hpp"

static char config_string[] = QUOTE(group: {
    int: 123;
    int64: 124L;
    bool: true;
    string: "bla";
    float: 1.2
  });

using namespace P::Conf;

TEST(TestConfig, test) {

    Config *config = conf_init();

    ASSERT_EQ(conf_read_string(config, config_string), true);

    ConfigSetting *group = conf_lookup(config, "group");

    ASSERT_EQ(conf_setting_get_int32(conf_setting_lookup_required(group, "int")), 123);
    ASSERT_EQ(conf_setting_get_int64(conf_setting_lookup_required(group, "int64")), 124);
    EXPECT_STREQ(conf_setting_get_string(conf_setting_lookup_required(group, "string")), "bla");
    ASSERT_EQ(conf_setting_get_bool(conf_setting_lookup_required(group, "bool")), true);
    ASSERT_FLOAT_EQ(conf_setting_get_float(conf_setting_lookup_required(group, "float")), 1.2);

    conf_destroy(config);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
