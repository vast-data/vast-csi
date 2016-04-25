/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>
#include <libconfig.h>

#include "plasma/execution/p_env.h"

static int init_calls = 0;
static int start_calls = 0;

void __wrap_p_module_start(void);
void __wrap_p_module_start()
{
    start_calls++;
}

void __wrap_p_module_init(void);
void __wrap_p_module_init()
{
    init_calls++;
}

static void test(void **state)
{
    (void) state;

    env_run("tests/test.config");
    assert_int_equal(init_calls, 2);
    assert_int_equal(start_calls, 2);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
