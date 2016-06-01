/* Copyright (C) Vast Data Ltd. */
#include <stddef.h>
#include <stdarg.h>
#include <setjmp.h>
#include <cmocka.h>

#include <p.h>
#include "plasma/execution/p_config_internal.h"

static void test_dbuffer_sanity(void **state)
{
    (void) state;

    PDbuffer *buf = p_dbuffer_init(2, 128);
    char data[] = "abcd";

    p_dbuffer_write(buf, &data, 4);
    p_dbuffer_write(buf, &data, 2);

    PDbufferReader reader;

    p_dbuffer_reader_init(&reader, buf);

    char out[4] = {0};
    P_DBUFFER_LENGTH_TYPE length;
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

    PDbuffer *buf = p_dbuffer_init(2, 32);
    char data[] = "abcdefgh";

    p_dbuffer_write(buf, &data, 8);
    p_dbuffer_write(buf, &data, 8);

    PDbufferReader reader;
    p_dbuffer_reader_init(&reader, buf);

    char out[8] = {0};
    P_DBUFFER_LENGTH_TYPE length;

    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_SUCCESS);
    assert_false(memcmp(data, out, 8));

    p_fill_zeroes(out, 8);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NEXT);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);

    assert_false(memcmp(data, out, 8));

    p_dbuffer_destroy(buf);
}

static void test_dbuffer_overflow_two_buffers(void **state)
{
    (void) state;

    PDbuffer *buf = p_dbuffer_init(2, 32);
    char data[] = "abcdefgh";

    PDbufferReader reader;
    p_dbuffer_reader_init(&reader, buf);

    p_dbuffer_write(buf, &data, 8);
    p_dbuffer_write(buf, &data, 8);
    p_dbuffer_write(buf, &data, 8);

    char out[8] = {0};
    P_DBUFFER_LENGTH_TYPE length;
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_OVERFLOW);
    assert_int_equal(length, 1);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_SUCCESS);
    assert_false(memcmp(data, out, 8));
    assert_int_equal(length, 8);

    p_fill_zeroes(out, 8);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NEXT);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);

    assert_false(memcmp(data, out, 8));
    assert_int_equal(length, 8);

    p_dbuffer_destroy(buf);
}

static void test_dbuffer_overflow_four_buffers(void **state)
{
    (void) state;

    PDbuffer *buf = p_dbuffer_init(4, 32);
    char data[] = "abcd";

    PDbufferReader reader;
    p_dbuffer_reader_init(&reader, buf);

    LOOP(5, i)
        p_dbuffer_write(buf, &data, 4);

    char out[4] = {0};
    P_DBUFFER_LENGTH_TYPE length;
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_OVERFLOW);
    assert_int_equal(length, 1);
    LOOP(3, i) {
        assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_SUCCESS);
        assert_false(memcmp(data, out, 4));
        assert_int_equal(length, 4);
        assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NEXT);
    }

    p_fill_zeroes(out, 4);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NOTHING);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, true), PDBUFFER_READ_SUCCESS);
    assert_false(memcmp(data, out, 4));
    assert_int_equal(length, 4);
    assert_int_equal(p_dbuffer_read(&reader, out, &length, false), PDBUFFER_READ_NOTHING);

    p_dbuffer_destroy(buf);
}

static char config_string[] = QUOTE(traces: {
    COMPONENT_PLASMA: {
      min_severity: "P_TRACE_DEBUG",
      buffer_size_mb: 1,
      persistent: true,
      file_size_mb: 2,
      file_count: 10
    }
  });

#define DATADIR "./testdata"
#define ITERS 10000000
static void test_emitter(void **state UNUSED)
{
    PConfig config;
    p_config_init(&config);

    assert_int_equal(config_read_string(&config, config_string), CONFIG_TRUE);

    PConfigSetting *setting = p_config_lookup(&config, "traces");

    PTraceEmitter *emitter = p_trace_emitter_init(setting);
    PTraceDumper *dumper = p_trace_dumper_init(setting, emitter, DATADIR);
    p_trace_emitter_set(emitter);
    p_trace_dumper_start(dumper);

    long l = 1;
    int i = 2;
    short s = 3;
    char c = '4';
    bool b = true;
    void *ptr = &l;
    const char *str = "ABC";
    float f = 1.2f;
    double d = 1.4;

    uint64_t start = p_get_clock_time_nano();
    LOOP(ITERS, _) {
        P_TRACE(P_TRACE_INFO, 0, "%ld %d %hd %c %p %s %f %lf %c", l, i, s, c, ptr, str, f, d, b);
    }
    uint64_t end = p_get_clock_time_nano();
    float avg = (float) (end - start) / ITERS;
    printf("Iterations: %d. Average: %.3fns. Total: %lu\n", ITERS, avg, end - start);

    P_TRACE(P_TRACE_INFO, 0, "Parameterless trace");
    const char *string = "Loooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooong";
    LOOP(10, _)
        P_TRACE(P_TRACE_INFO, 0, "Long trace: %s", string);

    p_trace_dumper_stop(dumper);
    p_trace_dumper_wait(dumper);
    p_trace_dumper_destroy(dumper);
    p_trace_emitter_destroy(emitter);
}

static void test_trace_file(void **state UNUSED)
{
    PTraceRecord record;
    PTraceFile *file = p_trace_file_init("bla", DATADIR, UNIT_MiB * 2, 3);
    LOOP(3000, _)
        p_trace_file_emit(file, &record, sizeof(record));
    p_trace_file_destroy(file);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_dbuffer_sanity),
        cmocka_unit_test(test_dbuffer_wraparound),
        cmocka_unit_test(test_dbuffer_overflow_two_buffers),
        cmocka_unit_test(test_dbuffer_overflow_four_buffers),
        cmocka_unit_test(test_emitter),
        cmocka_unit_test(test_trace_file)
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
