/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "globals.hpp"
#include "phys/layout/section_allocator.hpp"

using namespace Layout;

TEST(SectionAlloc, get_total_section_count)
{
    SectionAllocator allocator;
    allocator.init(0, ModuleId::I, FiberGroupId::I_CONTROL);
    allocator.do_activate(1024, 7);

    ASSERT_EQ(allocator.get_total_section_count(AddrType::WRITE_BUFFER), 2); // 3,6
    ASSERT_EQ(allocator.get_total_section_count(AddrType::HANDLE_TABLE), 5); // 1,2,4,5,7

    allocator.do_activate(1024, 6);

    ASSERT_EQ(allocator.get_total_section_count(AddrType::WRITE_BUFFER), 2);
    ASSERT_EQ(allocator.get_total_section_count(AddrType::HANDLE_TABLE), 4);
}

TEST(SectionAlloc, get_section_replication_factor)
{
    SectionAllocator allocator;
    allocator.init(0, ModuleId::I, FiberGroupId::I_CONTROL);

    ASSERT_EQ(allocator.get_section_replication_factor(1), ReplicationFactor::DUPLICATE);
    ASSERT_EQ(allocator.get_section_replication_factor(2), ReplicationFactor::DUPLICATE);
    ASSERT_EQ(allocator.get_section_replication_factor(3), ReplicationFactor::TRIPLICATE);
}

TEST(SectionAlloc, get_total_addr_type_size)
{
    SectionAllocator allocator;
    allocator.init(0, ModuleId::I, FiberGroupId::I_CONTROL);
    allocator.do_activate(2, 6);

    ASSERT_EQ(allocator.get_total_addr_type_size(0, AddrType::HANDLE_TABLE), UNIT_KiB * 4 * 4);
    ASSERT_EQ(allocator.get_total_addr_type_size(0, AddrType::WRITE_BUFFER), UNIT_MiB * 100 * 2);
}

TEST(SectionAlloc, translate)
{
    SectionAllocator allocator;
    allocator.init(0, ModuleId::I, FiberGroupId::I_CONTROL);

    uint64_t shards = 2048;
    uint64_t sections = 16;
    AddrType addr_type = AddrType::MD_BLOCKS;
    uint64_t block_count = 1024; // MD_BLOCKS block_count
    uint64_t block_size = 4 * UNIT_KiB;
    uint64_t start_offset = block_size * block_count + UNIT_KiB * 4 * block_count; // skip the HANDLE_TABLE + SHARD_MD

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
    // since there are 8 blocks per shard, we're still at the first section
    ASSERT_EQ(mio_address.section_id, 1);
    ASSERT_EQ(mio_address.byte_offset, start_offset + (2 + block_count) * block_size + 123);

    address.shard_id = 0;
    address.offset = block_size * 8 + 1;
    mio_address = allocator.translate(address, 1);
    // the offset doesn't fit in the first block, skip to the next group of block (2048 / 1024 = 2) and skip another section of triplets
    ASSERT_EQ(mio_address.section_id, 4);
    // skip the requested offset
    ASSERT_EQ(mio_address.byte_offset, start_offset + shards % block_count * block_size + 1);

    address.shard_id = 1;
    mio_address = allocator.translate(address, 1);
    ASSERT_EQ(mio_address.section_id, 4);
    ASSERT_EQ(mio_address.byte_offset, start_offset + shards % block_count * block_size + block_size + 1);
}

int main(int argc, char **argv) {
    global_test_mode = true;
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
