/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>
#include <libconfig.h>

#include "plasma/execution/p_env.h"

static void test(void **state)
{
    (void) state;

    env_run("tests/test.config");
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
