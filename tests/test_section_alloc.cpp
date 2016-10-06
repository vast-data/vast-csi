/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "phys/layout/section_allocator.hpp"

using namespace Layout;

TEST(SectionAlloc, translate)
{
    SectionAllocator layout;
    layout.init();
    layout.activate(100, 16);

    LAddress address;
    address.addr_type = AddrType::MD_BLOCKS;
    address.shard_id = 1;
    address.offset = 123;
    P::IO::MirroredAddressToken mio_address = layout.translate(address, 1);
    ASSERT_EQ(mio_address.section_id, 1);
    // skip the HANDLE_TABLE + SHARD_MD + one block of MD_BLOCKS + the requested offset
    ASSERT_EQ(mio_address.byte_offset, UNIT_MiB * 1024 + 4 * UNIT_KiB + 4 * UNIT_KiB + 123);

    address.shard_id = 257;
    mio_address = layout.translate(address, 1);
    ASSERT_EQ(mio_address.section_id, 2);
    // skip the HANDLE_TABLE + SHARD_MD + one block of MD_BLOCKS (shard_id % 256 = 1) + the requested offset
    ASSERT_EQ(mio_address.byte_offset, UNIT_MiB * 1024 + 4 * UNIT_KiB + 4 * UNIT_KiB + 123);

    /*address.shard_id = 0;
    address.offset = 4097;
    mio_address = layout.translate(address, 1);
    ASSERT_EQ(mio_address.section_id, 1);
    // skip the HANDLE_TABLE + SHARD_MD + one block of MD_BLOCKS + the requested offset
    ASSERT_EQ(mio_address.byte_offset, UNIT_MiB * 1024);*/
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
