/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "plasma/trace/dbuffer.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/memory/p_alloc.h"

using namespace P;
using namespace P::Trace;

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

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
