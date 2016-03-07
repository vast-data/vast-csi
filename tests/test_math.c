#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <cmocka.h>

#include "math.h"

static void test_add(void **state) {
    (void) state;

    assert_int_equal(add(2, 1), 3);
}

int main(void) {
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_add),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
