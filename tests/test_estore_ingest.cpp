#include <gtest/gtest.h>
#include <string.h>
#include "estore/ingest.hpp"
#include "plasma/utils/assert.hpp"
#include "estore/metadata/handles_table.hpp"
#include "utils.hpp"

using namespace EStore;
using EStoreRes::OK;
using P::IO::IOVec;
using P::IO::IOVecs;


TEST(TestCreate, test_ingest)
{
    EStoreIO eio;
    eio.init();

    ShardMd shard_md;
    shard_md.init(&eio);
    shard_md.create();

    HandlesTable handles_table;
    handles_table.init(&eio, &shard_md);
    EStoreRes res = handles_table.create();
    ASSERT(res == OK);

    Ingest ingest;
    ingest.init(&eio, &shard_md, &handles_table);

    res = ingest.create_root();
    ASSERT(res == OK);

    SettableAttr sattr;
    sattr.mode = 0444;
    sattr.flags = MODE;

    SystemAttr handle_attr;
    SystemAttr parent_pre_attr;
    SystemAttr parent_post_attr;
    EHandle handle;
    res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "baba", CreateFlags::HAS_CHILDREN, 0, &sattr, nullptr, nullptr,
                        &handle, &handle_attr, &parent_pre_attr, &parent_post_attr);
    ASSERT(res == OK);
    ASSERT_EQ(handle_attr.mode, sattr.mode);
    ASSERT_GT(parent_post_attr.mtime, parent_pre_attr.mtime);
    ASSERT_GT(parent_post_attr.ctime, parent_pre_attr.ctime);
    printf("created handle 0x%lx\n", handle);

    EHandle res_handle = 0;
    SystemAttr res_attr;
    SystemAttr parent_attr;

    res = ingest.lookup(nullptr, nullptr, ROOT_HANDLE, "gaga", false, &res_handle, &res_attr, &parent_attr);
    ASSERT(res == EStoreRes::NOENT);

    res = ingest.lookup(nullptr, nullptr, ROOT_HANDLE, "baba", false, &res_handle, &res_attr, &parent_attr);
    ASSERT(res == OK);
    ASSERT_EQ(res_handle, handle);
    ASSERT(memcmp(&res_attr, &handle_attr, sizeof(handle_attr)) == 0);
    ASSERT(memcmp(&parent_attr, &parent_post_attr, sizeof(parent_post_attr)) == 0);

    sattr.mode = 0555;
    sattr.uid = 7;
    sattr.gid = 7;
    sattr.flags = (AttrFlag)(MODE | UID | GID);
    res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "gamp", CreateFlags::HAS_CHILDREN, 0, &sattr, nullptr, nullptr,
                        &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(0555, handle_attr.mode);
    ASSERT_EQ(7, handle_attr.uid);
    ASSERT_EQ(7, handle_attr.gid);
    printf("created handle 0x%lx\n", handle);
    res = ingest.lookup(nullptr, nullptr, ROOT_HANDLE, "gamp", false, &res_handle, &res_attr, &parent_attr);
    ASSERT(res == OK);
    ASSERT_EQ(res_handle, handle);
    ASSERT(memcmp(&res_attr, &handle_attr, sizeof(handle_attr)) == 0);

    sattr.mode = 0333;
    res = ingest.create(nullptr, nullptr, handle, "bump", CreateFlags::HAS_CHILDREN, 0, &sattr, nullptr, nullptr,
                        &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(0333, handle_attr.mode);
    ASSERT_EQ(7, handle_attr.uid);
    ASSERT_EQ(7, handle_attr.gid);
    printf("created handle 0x%lx\n", handle);

    sattr.mode = 0333;
    res = ingest.create(nullptr, nullptr, handle, "data", CreateFlags::HAS_DATA, 0, &sattr, nullptr, nullptr,
                        &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(0333, handle_attr.mode);
    ASSERT_EQ(7, handle_attr.uid);
    ASSERT_EQ(7, handle_attr.gid);
    printf("created handle 0x%lx\n", handle);

    IOVec iovec[16];
    IOVecs iovecs;
    iovecs.iovecs = iovec;
    uint64_t offset = 0;
#define N_WRITES 100
    uint32_t lens[N_WRITES];
    LOOP(N_WRITES, i) {
        iovecs.count = 16;
        ingest.alloc_data_buffers(&iovecs);
        LOOP(iovecs.count, j) {
            memset(iovecs.iovecs[j].iov_base, i+1, DATA_BUFFER_SIZE);
        }
        lens[i] = rand() % (DATA_BUFFER_SIZE * 16);
        uint32_t len = lens[i];
        iovecs.count = 0;
        while (len > 0) {
            iovecs.iovecs[iovecs.count].iov_len = P_MIN(len, DATA_BUFFER_SIZE);
            len -= iovecs.iovecs[iovecs.count].iov_len;
            iovecs.count++;
        }
        res = ingest.write(nullptr, nullptr, handle, offset, &iovecs, nullptr, nullptr);
        ASSERT(res == OK);
        offset += lens[i];
    }

    res = ingest.get_attr(nullptr, nullptr, handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(handle_attr.size, offset);

    IOVecs alloc_vecs;
    offset = 0;
    uint32_t bytes_read;
    bool eof;
    // TODO check holes, reads should cover multiple writes, check overwrites
    LOOP(N_WRITES, i) {
        iovecs.count = 16;
        uint32_t read_offset = lens[i] - (rand() % (lens[i] / 2));
        printf("lens[i]=%u read_offset=%u\n", lens[i], read_offset);
        res = ingest.read(nullptr, nullptr, handle, offset + read_offset, lens[i] - read_offset, &iovecs, &alloc_vecs,
                          &bytes_read, &eof, nullptr, nullptr);
        ASSERT(res == OK);
        ASSERT_EQ(lens[i] - read_offset, bytes_read);
        if (i != N_WRITES - 1) {
            ASSERT_FALSE(eof);
        } else {
            ASSERT_TRUE(eof);
        }
        LOOP(iovecs.count, j) {
            LOOP(iovecs.iovecs[j].iov_len, k) {
                if ((char)(i+1) != ((char *)(iovecs.iovecs[j].iov_base))[k]) {
                    printf("i=%lu j=%lu k=%lu val=%hhu\n", i,j,k, ((char *)(iovecs.iovecs[j].iov_base))[k]);
                    PANIC("data cmp failure");
                }
            }
        }

        offset += lens[i];
        ingest.free_data_buffers(&alloc_vecs);
    }
}

int main(int argc, char **argv)
{
    Test::init_traces();
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
