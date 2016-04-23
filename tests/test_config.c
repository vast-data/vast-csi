/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

#include "plasma/execution/p_config_internal.h"

static char config_string[] = "group : {"
    "int: 123;"
    "int64: 124L;"
    "bool: true;"
    "string: \"bla\";"
    "float: 1.2"
    "}";

static void test(void **state)
{
    (void) state;

    PConfig config;
    p_config_init(&config);

    assert_int_equal(config_read_string(&config, config_string), CONFIG_TRUE);

    PConfigSetting *group = p_config_lookup(&config, "group");

    assert_int_equal(p_config_setting_get_int32(p_config_setting_lookup_required(group, "int")), 123);
    assert_int_equal(p_config_setting_get_int64(p_config_setting_lookup_required(group, "int64")), 124);
    assert_string_equal(p_config_setting_get_string(p_config_setting_lookup_required(group, "string")), "bla");
    assert_int_equal(p_config_setting_get_bool(p_config_setting_lookup_required(group, "bool")), true);
    assert_in_range(p_config_setting_get_float(p_config_setting_lookup_required(group, "float")), 1.1, 1.3);

    p_config_destroy(&config);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
