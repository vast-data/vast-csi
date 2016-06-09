/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "plasma/trace/dbuffer.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/trace/file.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/utils/units.hpp"
#include "plasma/utils/os.hpp"
#include "plasma/memory/alloc.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/execution/config_internal.hpp"

using namespace P;
using namespace P::Trace;
using namespace P::Conf;

#define CURRENT_COMPONENT ComponentId::PLASMA

TEST(DBuffer, sanity)
{
    DBuffer buf;
    buf.init(2, 128);
    byte data[] = "abcd";

    buf.write(data, 4);
    buf.write(data, 2);

    DBufferReader reader;
    reader.init(&buf);

    byte out[4] = {0};
    P_DBUFFER_LENGTH_TYPE length;
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NOTHING);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);
    ASSERT_EQ(length, 4);
    ASSERT_FALSE(memcmp(data, out, 4));

    p_fill_zeroes(out, 4);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);
    ASSERT_EQ(length, 2);
    ASSERT_FALSE(memcmp(data, out, 2));

    buf.destroy();
}

TEST(DBuffer, wraparound)
{
    DBuffer buf;
    buf.init(2, 32);

    byte data[] = "abcdefgh";

    buf.write(data, 8);
    buf.write(data, 8);

    DBufferReader reader;
    reader.init(&buf);

    byte out[8] = {0};
    P_DBUFFER_LENGTH_TYPE length;

    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::SUCCESS);
    ASSERT_FALSE(memcmp(data, out, 8));

    p_fill_zeroes(out, 8);
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NEXT);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);

    ASSERT_FALSE(memcmp(data, out, 8));

    buf.destroy();
}

TEST(DBuffer, overflow_two_buffers)
{
    DBuffer buf;
    buf.init(2, 32);

    byte data[] = "abcdefgh";

    DBufferReader reader;
    reader.init(&buf);

    buf.write(data, 8);
    buf.write(data, 8);
    buf.write(data, 8);

    byte out[8] = {0};
    P_DBUFFER_LENGTH_TYPE length;
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::OVERFLOW);
    ASSERT_EQ(length, 1);
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::SUCCESS);
    ASSERT_FALSE(memcmp(data, out, 8));
    ASSERT_EQ(length, 8);

    p_fill_zeroes(out, 8);
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NEXT);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);

    ASSERT_FALSE(memcmp(data, out, 8));
    ASSERT_EQ(length, 8);

    buf.destroy();
}

TEST(DBuffer, overflow_four_buffers)
{
    DBuffer buf;
    buf.init(4, 32);
    byte data[] = "abcd";

    DBufferReader reader;
    reader.init(&buf);

    LOOP(5, i)
        buf.write(data, 4);

    byte out[4] = {0};
    P_DBUFFER_LENGTH_TYPE length;
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::OVERFLOW);
    ASSERT_EQ(length, 1);
    LOOP(3, i) {
        ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::SUCCESS);
        ASSERT_FALSE(memcmp(data, out, 4));
        ASSERT_EQ(length, 4);
        ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NEXT);
    }

    p_fill_zeroes(out, 4);
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NOTHING);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);
    ASSERT_FALSE(memcmp(data, out, 4));
    ASSERT_EQ(length, 4);
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NOTHING);

    buf.destroy();
}

static char config_string[] = QUOTE(traces: {
    PLASMA: {
        min_severity: "SEVERITY_DEBUG",
        buffer_size_mb: 1,
        persistent: true,
        file_size_mb: 2,
        file_count: 10
      }
    });

TEST(Trace, emitter)
{
    Config* conf = conf_init();

    ASSERT_EQ(conf_read_string(conf, config_string), true);

    ConfigSetting *setting = conf_lookup(conf, "traces");

    Emitter emitter;
    emitter.init(setting);
    emitter.set();

    long l = 1;
    int i = 2;
    void *ptr = &l;
    const char *str = "ABC";
    float f = 1.2f;

    PT_INFO("Int: %d. Long: %ld. Ptr: %p. Str: %s. Float: %f", i, l, ptr, str, f);

    emitter.destroy();
    conf_destroy(conf);
}

TEST(Trace, file)
{
    ensure_directory_exists("build/testdata");

    TraceRecord record;
    TraceFile file;
    file.init("test", "build/testdata", UNIT_MiB * 2, 3);
    LOOP(2000, _)
        file.emit(&record, sizeof(record) - 3);
    file.destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
