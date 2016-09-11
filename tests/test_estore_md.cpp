/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include <estore/metadata/data_content_block.hpp>
#include "estore/metadata/data_range_block.hpp"
#include "estore/metadata/data_bitmap_block.hpp"
#include "estore/metadata/composite_block.hpp"
#include "estore/metadata/handles_table.hpp"
#include "estore/metadata/handle_block.hpp"
#include "estore/metadata/name_bitmap_block.hpp"
#include "estore/metadata/name_content_block.hpp"
#include "estore/io/buffers_guard.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/utils/units.hpp"
#include "estore/metadata/name_range_block.hpp"
#include "utils.hpp"

using namespace EStore;
using EStoreRes::OK;

#define ASSERT_OK(RES) \
    ASSERT(RES == OK, "operation failed res=" << (uint64_t)res);

class TestMIOBuffer : public MIOBuffer {
public:
    TestMIOBuffer() {
        MIOBuffer::init((P::byte *)aligned_alloc(IO_ALIGNMENT, NVRAM_MD_BLOCK_SIZE), NVRAM_MD_BLOCK_SIZE);
    }

    ~TestMIOBuffer() {
        free(get_mio_vec()->iov_base);
    }
};

static void fill_range_block(NameRangeBlock *range_block)
{
    EAddress addr {
        .addr_type = EAddrType::WRITE_BUFFER,
        .shard_id = 0,
        .offset = 0,
    };
    ASSERT(EStoreRes::OK == range_block->add_range("aaa", addr));
    addr.shard_id = 3;
    ASSERT(EStoreRes::OK == range_block->add_range("z", addr));
    addr.shard_id = 1;
    ASSERT(EStoreRes::OK == range_block->add_range("bbb", addr));
    addr.shard_id = 2;
    ASSERT(EStoreRes::OK == range_block->add_range("ddasSDKJLHasnds,anfladj", addr));
}

TEST(TestNameRangeBlock, test_md)
{
    TestMIOBuffer buff;
    NameRangeBlock range_block;
    range_block.init(&buff);
    ASSERT(range_block.get_type() == BlockType::NAME_RANGE_BLOCK);

    fill_range_block(&range_block);
    EAddress addr_res = range_block.get_address("aab");
    ASSERT_EQ(addr_res.shard_id, 0);
    addr_res = range_block.get_address("ccc");
    ASSERT_EQ(addr_res.shard_id, 1);
    addr_res = range_block.get_address("fgrhaydajflsdkjfj");
    ASSERT_EQ(addr_res.shard_id, 2);
    addr_res = range_block.get_address("za");
    ASSERT_EQ(addr_res.shard_id, 3);
}

TEST(TestDataRangeBlock, test_md)
{
    TestMIOBuffer buff;
    DataRangeBlock range_block;
    range_block.init(&buff);
    ASSERT(range_block.get_type() == BlockType::DATA_RANGE_BLOCK);

    EAddress addr {
        .addr_type = EAddrType::CONTAINED,
        .shard_id = 0,
        .offset = 0,
    };
    EStoreRes res = range_block.add_range(0, addr);
    ASSERT_OK(res);
    EAddress res_addr = range_block.get_range(0);
    ASSERT_EQ(addr.as_number(), res_addr.as_number());
    res_addr = range_block.get_range(2000);
    ASSERT_EQ(addr.as_number(), res_addr.as_number());

    addr.offset = 7;
    res = range_block.add_range(1000, addr);
    ASSERT_OK(res);
    res_addr = range_block.get_range(2000);
    ASSERT_EQ(addr.as_number(), res_addr.as_number());

    addr.offset = 9132;
    res = range_block.add_range(500, addr);
    res_addr = range_block.get_range(700);
    ASSERT_EQ(addr.as_number(), res_addr.as_number());

    LOOP(10000, i) {
        res = range_block.add_range(i, addr);
        ASSERT(res == OK || res == EStoreRes::NO_MEM);
        if (res == EStoreRes::NO_MEM) {
            break;
        }
    }
    ASSERT(res == EStoreRes::NO_MEM);
}


TEST(TestExtent, test_md)
{
    P::Extent<uint64_t> extent;
    extent._offset = 0;
    extent._len = 4;
    ASSERT(!extent.overlaps(4, 4));
    ASSERT(extent.adjacent_overlap(4, 4));
    ASSERT(extent.overlaps(3, 4));
    ASSERT(extent.overlaps(1, 1));

    extent._offset = 4;
    ASSERT(!extent.overlaps(0, 4));
    ASSERT(!extent.overlaps(8, 4));
    ASSERT(extent.adjacent_overlap(0, 4));
    ASSERT(extent.adjacent_overlap(8, 4));
    ASSERT(extent.overlaps(7, 4));

    extent.merge(0, 5);
    ASSERT_EQ(extent._offset, 0);
    ASSERT_EQ(extent._len, 8);

    extent._offset = 4;
    extent._len = 4;
    extent.merge(0, 4);
    ASSERT_EQ(extent._offset, 0);
    ASSERT_EQ(extent._len, 8);

    extent._offset = 4;
    extent._len = 4;
    extent.merge(8, 8);
    ASSERT_EQ(extent._offset, 4);
    ASSERT_EQ(extent._len, 12);

    extent._offset = 4;
    extent._len = 4;
    extent.merge(6, 4);
    ASSERT_EQ(extent._offset, 4);
    ASSERT_EQ(extent._len, 6);

    extent._offset = 4;
    extent._len = 10;
    extent.merge(6, 4);
    ASSERT_EQ(extent._offset, 4);
    ASSERT_EQ(extent._len, 10);

    P::Extent<uint64_t> extent1;
    extent1._offset = 10;
    extent1._len = 10;
    P::Extent<uint64_t> extent2;
    extent2._offset = 10;
    extent2._len = 10;
    ASSERT(extent1.contained_by(&extent2));
    ASSERT(extent1.contains(&extent2));

    extent2._offset = 11;
    extent2._len = 10;
    ASSERT(extent1.overlaps(&extent2));
    ASSERT(!extent1.contained_by(&extent2));
    ASSERT(!extent1.contains(&extent2));

    extent2._offset = 11;
    extent2._len = 8;
    ASSERT(extent1.contains(&extent2));
    ASSERT(!extent1.contained_by(&extent2));

    extent2._offset = 15;
    extent2._len = 10;
    extent1.crop(&extent2);
    ASSERT_EQ(extent1._offset, 10);
    ASSERT_EQ(extent1._len, 5);

    extent1._offset = 10;
    extent1._len = 10;
    extent2._offset = 5;
    extent2._len = 10;
    extent1.crop(&extent2);
    ASSERT_EQ(extent1._offset, 15);
    ASSERT_EQ(extent1._len, 5);

    extent1._offset = 10;
    extent1._len = 10;
    extent2._offset = 11;
    extent2._len = 10;
    extent1.crop(&extent2);
    ASSERT_EQ(extent1._offset, 10);
    ASSERT_EQ(extent1._len, 1);

    extent1._offset = 10;
    extent1._len = 10;
    extent2._offset = 1;
    extent2._len = 100;
    extent1.intersect(&extent2);
    ASSERT_EQ(extent1._offset, 10);
    ASSERT_EQ(extent1._len, 10);

    extent1._offset = 10;
    extent1._len = 10;
    extent2._offset = 5;
    extent2._len = 10;
    extent1.intersect(&extent2);
    ASSERT_EQ(extent1._offset, 10);
    ASSERT_EQ(extent1._len, 5);

    extent1._offset = 10;
    extent1._len = 10;
    extent2._offset = 15;
    extent2._len = 10;
    extent1.intersect(&extent2);
    ASSERT_EQ(extent1._offset, 15);
    ASSERT_EQ(extent1._len, 5);
}

#define MAX_ADDRESSES 64
TEST(TestDataBitmapBlock, test_md)
{
    TestMIOBuffer buff;
    DataBitmapBlock bitmap_block;
    bitmap_block.init(&buff);
    bitmap_block.set_base_offset(0);

    EAddress addr = { EAddrType::CONTAINED, 5, 6 };
    EStoreRes res = bitmap_block.add_extent(0, 4, addr);
    ASSERT_OK(res);
    res = bitmap_block.add_extent(3, 8, addr);
    ASSERT_OK(res);

    res = bitmap_block.add_extent(10, 8, addr);
    ASSERT_OK(res);

    EAddress addresses[MAX_ADDRESSES];
    uint16_t n_addrs = MAX_ADDRESSES;
    res = bitmap_block.get_content_addrs(1, 5, &n_addrs, addresses);
    ASSERT_OK(res);
    ASSERT_EQ(1, n_addrs);
    ASSERT(memcmp(&addr, &addresses[0], sizeof(addr)) == 0);

    res = bitmap_block.add_extent(100, 8, addr);
    ASSERT_OK(res);
    EAddress addr2 = { EAddrType::CONTAINED, 51, 36 };
    res = bitmap_block.add_extent(100, 8, addr2);
    ASSERT_OK(res);

    n_addrs = MAX_ADDRESSES;
    res = bitmap_block.get_content_addrs(0, 5000, &n_addrs, addresses);
    ASSERT_OK(res);
    ASSERT_EQ(3, n_addrs);
    ASSERT(memcmp(&addr, &addresses[0], sizeof(addr)) == 0);
    ASSERT(memcmp(&addr, &addresses[1], sizeof(addr)) == 0);
    ASSERT(memcmp(&addr2, &addresses[2], sizeof(addr)) == 0);

    n_addrs = MAX_ADDRESSES;
    res = bitmap_block.get_content_addrs(100, 5000, &n_addrs, addresses);
    ASSERT_OK(res);
    ASSERT_EQ(2, n_addrs);
}

TEST(TestNameHash, test_md)
{
    TestMIOBuffer buff;
    NameBitmapBlock bitmap_block;
    bitmap_block.init(&buff);
    ASSERT(bitmap_block.get_type() == BlockType::NAME_BITMAP_BLOCK);

    EAddress addr {
        .addr_type = EAddrType::WRITE_BUFFER,
        .shard_id = 0,
        .offset = 0,
    };
    ASSERT(EStoreRes::OK == bitmap_block.add_name("aaa", addr));
    addr.shard_id = 1;
    ASSERT(EStoreRes::OK == bitmap_block.add_name("adsasdsa", addr));
    addr.shard_id = 2;
    ASSERT(EStoreRes::OK == bitmap_block.add_name("zdfgsdew", addr));
    addr.shard_id = 3;
    ASSERT(EStoreRes::OK == bitmap_block.add_name("2314351cf", addr));

    EAddress addr_res;
    ASSERT(EStoreRes::OK == bitmap_block.get_addr("2314351cf", &addr_res));
    ASSERT_EQ(3, addr_res.shard_id);
    ASSERT(EStoreRes::OK == bitmap_block.get_addr("adsasdsa", &addr_res));
    ASSERT_EQ(1, addr_res.shard_id);

    ASSERT(EStoreRes::NOENT == bitmap_block.get_addr("adljklasdfafsasdsa", &addr_res));
}

TEST(TestNameContent, test_md)
{
    TestMIOBuffer buff;
    NameContentBlock content_block;
    content_block.init(&buff);
    ASSERT(content_block.get_type() == BlockType::NAME_CONTENT_BLOCK);

    EHandle handle = 0;
    ASSERT(EStoreRes::OK == content_block.add_handle("aaa", handle));
    handle = 1;
    ASSERT(EStoreRes::OK == content_block.add_handle("bbb", handle));
    handle = 2;
    ASSERT(EStoreRes::OK == content_block.add_handle("jhlkjhl", handle));

    EHandle handle_res;
    ASSERT(EStoreRes::OK == content_block.get_handle("aaa", &handle_res));
    ASSERT_EQ(0, handle_res);
    ASSERT(EStoreRes::OK == content_block.get_handle("bbb", &handle_res));
    ASSERT_EQ(1, handle_res);

    ASSERT(EStoreRes::NOENT == content_block.get_handle("adljklasdfafsasdsa", &handle_res));
}

#define N_CONTENT_EXTENTS 8
TEST(TestDataContent, test_md)
{
    TestMIOBuffer buff;
    DataContentBlock content_block;
    content_block.init(&buff);
    ASSERT(content_block.get_type() == BlockType::DATA_CONTENT_BLOCK);

    EAddress data_addr = {EAddrType::CONTAINED, 0, 0};
    EStoreRes res = content_block.add_extent(8, 1 ,2, data_addr);
    ASSERT_OK(res);
    res = content_block.add_extent(8, 2 ,6, data_addr);
    ASSERT_OK(res);
    res = content_block.add_extent(7, 2 ,6, data_addr);
    ASSERT_OK(res);

    uint16_t n_extents = N_CONTENT_EXTENTS;
    ContentExtent extents[N_CONTENT_EXTENTS];
    res = content_block.get_extents(8, 0, 1000, &n_extents, extents);
    ASSERT_OK(res);
    ASSERT(n_extents == 2);
    n_extents = N_CONTENT_EXTENTS;
    res = content_block.get_extents(7, 0, 1000, &n_extents, extents);
    ASSERT_OK(res);
    ASSERT(n_extents == 1);

    LOOP(1, j) {
        ExtentsContainer extents_container;
        extents_container.init(0, 400);
        content_block.init(&buff);
        EHandle handle = 1;
        data_addr = {EAddrType::CONTAINED, 0, 0};
        LOOP(100, i) {
            uint32_t len = rand() % 100 + 1;
            data_addr.offset += len;
            res = content_block.add_extent(handle, rand() % 400, len, data_addr);
            ASSERT_OK(res);
        }
        res = content_block.export_extents(handle, 0, 1000, &extents_container);
        ASSERT_OK(res);
        extents_container.sanity_check();
        extents_container.trace();
    }
}

TEST(TestHandleBlock, test_md)
{
    TestMIOBuffer buff;
    HandleBlock handle_block;
    handle_block.init(&buff);
    ASSERT(handle_block.get_type() == BlockType::HANDLE_BLOCK);

    handle_block.set_handle(7);
    ASSERT_EQ(7, handle_block.get_handle());

    SystemAttr *attr = handle_block.get_attr();
    memset(attr, 0, sizeof(*attr));
}

TEST(TestCompositeBlock, test_md)
{
    EStoreIO eio;
    eio.init();

    BuffersGuard buffers_guard(&eio, 5);
    EHandle handle = 9;
    CompositeBlock composite_block;
    composite_block.init(buffers_guard.get_next());

    HandleBlock handle_block;
    handle_block.init(buffers_guard.get_next());
    ASSERT(handle_block.get_type() == BlockType::HANDLE_BLOCK);
    handle_block.set_handle(handle);
    ASSERT(EStoreRes::OK == composite_block.add_contained_block(handle, &handle_block));

    NameRangeBlock range_block;
    range_block.init(buffers_guard.get_next());
    ASSERT(range_block.get_type() == BlockType::NAME_RANGE_BLOCK);
    fill_range_block(&range_block);
    ASSERT(EStoreRes::OK == composite_block.add_contained_block(handle, &range_block));

    NameBitmapBlock bitmap_block;
    bitmap_block.init(buffers_guard.get_next());
    ASSERT(bitmap_block.get_type() == BlockType::NAME_BITMAP_BLOCK);
    EAddress addr1 = {
        .addr_type = EAddrType::CONTAINED,
        .offset = 1,
        .shard_id = 2
    };
    EStoreRes res = bitmap_block.add_name("asasa", addr1);
    ASSERT_OK(res);
    ASSERT(EStoreRes::OK == composite_block.add_contained_block(handle, &bitmap_block));

    NameRangeBlock res_block1;
    ASSERT(EStoreRes::NOENT == composite_block.export_contained_block(handle + 1, BlockType::NAME_RANGE_BLOCK, &res_block1));
    ASSERT(EStoreRes::OK == composite_block.export_contained_block(handle, BlockType::NAME_RANGE_BLOCK, &res_block1));

    ASSERT_EQ(res_block1.get_used_bytes(), range_block.get_used_bytes());
    ASSERT_EQ(res_block1.get_used_bytes(), res_block1.get_size());
    ASSERT_EQ(0, res_block1.space_left());

    res_block1.replace_buffer(buffers_guard.get_next());
    EAddress addr {
        .addr_type = EAddrType::WRITE_BUFFER,
        .shard_id = 8,
        .offset = 0,
    };
    ASSERT(EStoreRes::OK == res_block1.add_range("batata", addr));
    ASSERT(EStoreRes::OK == composite_block.replace_contained_block(handle, &res_block1));

    NameRangeBlock res_block2;
    ASSERT(EStoreRes::OK == composite_block.export_contained_block(handle, BlockType::NAME_RANGE_BLOCK, &res_block2));

    ASSERT(res_block2.get_type() == BlockType::NAME_RANGE_BLOCK);
    EAddress addr2 = res_block2.get_address("batata");
    ASSERT_EQ(addr.as_number(), addr2.as_number());
}

#define BUCKET_SIZE 1024
TEST(TestHandlesTable, test_md)
{
    EStoreIO eio;
    eio.init();

    ShardMd shard_md;
    shard_md.init(&eio);
    shard_md.create();

    HandlesTable handles_table;
    handles_table.init(&eio, &shard_md);

    EStoreRes res = handles_table.create();
    ASSERT_OK(res);

    EHandle handle = 8;
    TestMIOBuffer cbuff;
    CompositeBlock composite_block;
    composite_block.init(&cbuff);

    TestMIOBuffer hbuff;
    HandleBlock handle_block;
    handle_block.init(&hbuff);
    ASSERT(handle_block.get_type() == BlockType::HANDLE_BLOCK);
    handle_block.set_handle(handle);
    handle_block.get_attr()->atime = 999;
    ASSERT(EStoreRes::OK == composite_block.add_contained_block(handle, &handle_block));

    res = handles_table.write(handle, composite_block.get_buffer());
    ASSERT_OK(res);

    memset(cbuff.get_data(), 0, sizeof(BUCKET_SIZE));
    composite_block.init(&cbuff);
    res = handles_table.read(handle, composite_block.get_buffer());
    ASSERT_OK(res);

    ASSERT_OK(composite_block.export_contained_block(handle, BlockType::HANDLE_BLOCK, &handle_block));
    ASSERT_EQ(999, handle_block.get_attr()->atime);
}

int main(int argc, char **argv)
{
    srand(time(0));
    Test::init_traces();
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
