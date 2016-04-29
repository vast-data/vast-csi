/* Copyright (C) Vast Data Ltd. */
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

#include "plasma/trace/p_dbuffer.h"

static void test_dbuffer_sanity(void **state)
{
    (void) state;

    PDbuffer *buf = p_dbuffer_init(128);
    char data[] = "abcd";

    p_dbuffer_write(buf, &data, 4);
    p_dbuffer_write(buf, &data, 2);

    PDbufferReader reader;

    p_dbuffer_reader_init(&reader, buf);

    char out[4] = {0};
    uint8_t length;
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NOTHING);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);
    assert_int_equal(length, 4);
    assert_false(memcmp(data, out, 4));

    p_fill_zeroes(out, 4);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);
    assert_int_equal(length, 2);
    assert_false(memcmp(data, out, 2));

    p_dbuffer_destroy(buf);
}

static void test_dbuffer_wraparound(void **state)
{
    (void) state;

    PDbuffer *buf = p_dbuffer_init(32);
    char data[] = "abcdefgh";

    p_dbuffer_write(buf, &data, 8);
    p_dbuffer_write(buf, &data, 8);

    PDbufferReader reader;
    p_dbuffer_reader_init(&reader, buf);

    char out[8] = {0};
    uint8_t length;

    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_SUCCESS);
    assert_false(memcmp(data, out, 8));

    p_fill_zeroes(out, 8);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NOTHING);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);

    assert_false(memcmp(data, out, 8));

    p_dbuffer_destroy(buf);
}

static void test_dbuffer_overflow(void **state)
{
    (void) state;

    PDbuffer *buf = p_dbuffer_init(32);
    char data[] = "abcdefgh";

    PDbufferReader reader;
    p_dbuffer_reader_init(&reader, buf);

    p_dbuffer_write(buf, &data, 8);
    p_dbuffer_write(buf, &data, 8);
    p_dbuffer_write(buf, &data, 8);

    char out[8] = {0};
    uint8_t length;
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_OVERFLOW);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_SUCCESS);
    assert_false(memcmp(data, out, 8));
    assert_int_equal(length, 8);

    p_fill_zeroes(out, 8);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NOTHING);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);

    assert_false(memcmp(data, out, 8));
    assert_int_equal(length, 8);

    p_dbuffer_destroy(buf);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_dbuffer_sanity),
        cmocka_unit_test(test_dbuffer_wraparound),
        cmocka_unit_test(test_dbuffer_overflow)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
