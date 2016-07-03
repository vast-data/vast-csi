/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include <thread>

#include "plasma/trace/dbuffer.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/trace/file.hpp"
#include "plasma/trace/dumper.hpp"
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

    P::fill_zeroes(out, 4);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);
    ASSERT_EQ(length, 2);
    ASSERT_FALSE(memcmp(data, out, 2));

    buf.destroy();
}

TEST(DBuffer, wraparound)
{
    DBuffer buf;
    buf.init(2, 32);

    byte data1[] = "abcdefgh";
    byte data2[] = "klmnopqr";

    buf.write(data1, 8);
    buf.write(data2, 8);

    DBufferReader reader;
    reader.init(&buf);

    byte out[8] = {0};
    P_DBUFFER_LENGTH_TYPE length;

    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::SUCCESS);
    ASSERT_FALSE(memcmp(data1, out, 8));

    P::fill_zeroes(out, 8);
    ASSERT_EQ(reader.read(out, &length, false), DBufferReader::ReadResult::NEXT);
    ASSERT_EQ(reader.read(out, &length, true), DBufferReader::ReadResult::SUCCESS);

    ASSERT_FALSE(memcmp(data2, out, 8));

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

    P::fill_zeroes(out, 8);
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

    P::fill_zeroes(out, 4);
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
    emitter.init(setting, false);
    emitter.set_local();

    long l = 1;
    int i = 2;
    short s = 3;
    char c = '4';
    bool b = true;
    void *ptr = &l;
    const char *str = "ABC";

    float f = 1.2f;
    double d = 1.4;

    PT_INFO("Parameterless trace");
    LOOP(1000000, _)
        PT_INFO("%ld %d %hd %c %p %s %f %lf %c", l, i, s, c, ptr, str, f, d, b);

    byte string[5000];
    LOOP(4998, index)
        string[index] = 'a';
    string[4999] = '\0';

    LOOP(10, _)
        PT_INFO("Long trace: %s", (char*) string);

    emitter.destroy();
    conf_destroy(conf);
}

#define DATADIR "data/traces"

TEST(Trace, dumper)
{
    Config* conf = conf_init();

    ASSERT_EQ(conf_read_string(conf, config_string), true);

    ConfigSetting *setting = conf_lookup(conf, "traces");

    Emitter emitter;
    emitter.init(setting, false);

    Dumper dumper;
    dumper.init(setting, &emitter, DATADIR);

    emitter.set_local();
    dumper.start();

    LOOP(1000000, i)
        PT_INFO("Kawabanga: %ld!.", i);

    dumper.stop();
    dumper.wait();

    dumper.destroy();
    emitter.destroy();
    conf_destroy(conf);
}

void trace_func()
{
    auto s1 = "abcdefghijklmnopqrstuvwxyz";
    auto s2 = "abcdefghijklmnopqrstuvwxyz123456789";
    LOOP(1000000, i)
        PT_INFO("Kawabanga: %ld %s!", i, i % 2 ? s1 : s2);
}

TEST(Trace, concurrent_dumper)
{
    Config* conf = conf_init();

    ASSERT_EQ(conf_read_string(conf, config_string), true);

    ConfigSetting *setting = conf_lookup(conf, "traces");

    Emitter emitter;
    emitter.init(setting, true);

    Dumper dumper;
    dumper.init(setting, &emitter, DATADIR);

    emitter.set_global();
    dumper.start();

    std::thread t1(trace_func);
    std::thread t2(trace_func);

    t1.join();
    t2.join();

    dumper.stop();
    dumper.wait();

    dumper.destroy();
    emitter.destroy();
    conf_destroy(conf);
}

TEST(Trace, file)
{
    ensure_directory_exists(DATADIR);

    static TraceInfo TRACE_SECTION trace_info = {
        "Test trace file.", __FILE__, "<temp>", __LINE__, __func__
    };
    uint16_t info_index = get_trace_info_index(&trace_info);

    TraceRecord record;
    record.info_index = info_index;

    TraceFile file;
    file.init("test", DATADIR, UNIT_MiB * 2, 3);
    LOOP(2000, _)
        file.emit(&record, offsetof(TraceRecord, params));
    file.destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
