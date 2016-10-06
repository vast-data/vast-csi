/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "phys/layout/section_allocator.hpp"

using namespace Layout;

TEST(SectionAlloc, translate)
{
    SectionAllocator allocator;
    allocator.init(0, ModuleId::I, FiberGroupId::I_CONTROL);

    uint64_t shards = 1000;
    uint64_t sections = 16;
    AddrType addr_type = AddrType::MD_BLOCKS;
    uint64_t block_count = 256; // MD_BLOCKS block_count
    uint64_t block_size = 4 * UNIT_KiB;
    uint64_t start_offset = UNIT_MiB * 1024 + UNIT_KiB * 4; // skip the HANDLE_TABLE + SHARD_MD

    allocator.do_activate(shards, sections);

    LAddress address;
    address.addr_type = addr_type;
    address.shard_id = 1;
    address.offset = 123;

    ASSERT_DEATH(allocator.translate(address, block_size + 1), "PANIC");

    P::IO::MirroredAddressToken mio_address = allocator.translate(address, 1);
    ASSERT_EQ(mio_address.section_id, 1);
    // skip one block for one shard and the requested offset
    ASSERT_EQ(mio_address.byte_offset, start_offset + block_size + 123);

    address.shard_id = 2 + block_count;
    mio_address = allocator.translate(address, 1);
    // skip one section because of shard_id / block_count == 1
    ASSERT_EQ(mio_address.section_id, 2);
    // skip two blocks (shard_id % block_count = 2) and the requested offset
    ASSERT_EQ(mio_address.byte_offset, start_offset + 2 * block_size + 123);

    address.shard_id = 0;
    address.offset = block_size + 1;
    mio_address = allocator.translate(address, 1);
    // the offset doesn't fit in the first block, skip to the next group of block (1000 / 256 = 3) and skip another section of triplets
    ASSERT_EQ(mio_address.section_id, 5);
    // skip the requested offset
    ASSERT_EQ(mio_address.byte_offset, start_offset + shards % block_count * block_size + 1);

    address.shard_id = 1;
    mio_address = allocator.translate(address, 1);
    ASSERT_EQ(mio_address.section_id, 5);
    ASSERT_EQ(mio_address.byte_offset, start_offset + shards % block_count * block_size + block_size + 1);
}

int main(int argc, char **argv) {
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
