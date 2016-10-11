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

#define CURRENT_COMPONENT ComponentId::TEST
#define CURRENT_CHANNEL DATA

static bool list_callback(ListEntry *entry, void *ctx)
{
    uint64_t *n_files = (uint64_t *)ctx;
    PTC_DEBUG("got element handle=0x%lx name=%s offset=0x%lx n_files=%lu",
              entry->handle, entry->name, entry->offset, *n_files);
    (*n_files)++;
    return true;
}

TEST(TestList, test_ingest)
{
    // TODO use setup
    EStoreIO eio;
    eio.init(0, ModuleId::I, FiberGroupId::I_CONTROL, nullptr);

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

    char name[64];
    SettableAttr sattr;
    sattr.mode = 0444;
    sattr.flags = MODE;
    SystemAttr handle_attr;
    SystemAttr parent_pre_attr;
    SystemAttr parent_post_attr;
    EHandle handle;

#define N_FILES 700
    LOOP(N_FILES, i) {
        sprintf(name, "file_%lu", i);
        res = ingest.create(nullptr, nullptr, ROOT_HANDLE, name, CreateFlags::HAS_CHILDREN, 0, &sattr, nullptr,
                            nullptr, &handle, &handle_attr, &parent_pre_attr, &parent_post_attr);
        ASSERT(res == OK);
    }

    uint64_t n_files = 0;
    uint64_t curr_version = 0;
    res = ingest.list_elements(nullptr, nullptr, ROOT_HANDLE, 0, 0, list_callback, &n_files, nullptr, 0, &curr_version,
                               nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(n_files, N_FILES);

    eio.destroy();
}

TEST(TestCreate, test_ingest)
{
    EStoreIO eio;
    eio.init(0, ModuleId::I, FiberGroupId::I_CONTROL, nullptr);

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
    PTC_DEBUG("created handle 0x%lx", handle);

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

    EHandle parent;
    res = ingest.lookup_parent(nullptr, nullptr, res_handle, &parent, &res_attr, &parent_attr);
    ASSERT(res == OK);
    ASSERT_EQ(parent, ROOT_HANDLE);

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
    PTC_DEBUG("created handle 0x%lx", handle);
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
    PTC_DEBUG("created handle 0x%lx", handle);

    eio.destroy();
}

TEST(TestIO, test_ingest)
{
    EStoreIO eio;
    eio.init(0, ModuleId::I, FiberGroupId::I_CONTROL, nullptr);

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
    sattr.flags = MODE;
    sattr.mode = 0333;
    EHandle handle;
    SystemAttr handle_attr;
    res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "data", CreateFlags::HAS_DATA, 0, &sattr, nullptr, nullptr,
                        &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    PTC_DEBUG("created handle 0x%lx", handle);

    #define WRITE_SIZE_FACTOR 12
    #define IOVEC_SIZE 64
    IOVec iovec[IOVEC_SIZE];
    IOVecs iovecs;
    iovecs.iovecs = iovec;
    uint64_t offset = 0;

    #define N_WRITES 20000
    uint32_t lens[N_WRITES];
    LOOP(N_WRITES, i) {
        lens[i] = rand() % (DATA_BUFFER_SIZE * WRITE_SIZE_FACTOR) + 1;
        uint32_t len = lens[i];
        iovecs.count = (len / DATA_BUFFER_SIZE) + (len % DATA_BUFFER_SIZE ? 1 : 0);
        ingest.alloc_data_buffers(&iovecs);
        LOOP(iovecs.count, j) {
            memset(iovecs.iovecs[j].iov_base, i+1, DATA_BUFFER_SIZE);
            iovecs.iovecs[j].iov_len = P_MIN(len, DATA_BUFFER_SIZE);
            len -= iovecs.iovecs[j].iov_len;
        }
        ASSERT_EQ(lens[i], iovecs.total_length());
        res = ingest.write(nullptr, nullptr, handle, offset, &iovecs, nullptr, nullptr);
        ASSERT(res == OK);
        offset += lens[i];

        if (i % 1000 == 0) {
            res = ingest.get_attr(nullptr, nullptr, handle, &handle_attr, nullptr, nullptr);
            ASSERT(res == OK);
            ASSERT_EQ(handle_attr.size, offset);
        }
    }
    res = ingest.get_attr(nullptr, nullptr, handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(handle_attr.size, offset);

    IOVecs alloc_vecs;
    offset = 0;
    uint32_t bytes_read;
    bool eof;
    // TODO check holes, reads should cover multiple writes, check overwrites, test vec len being too small
    LOOP(N_WRITES, i) {
        iovecs.iovecs = iovec;
        iovecs.count = IOVEC_SIZE;
        uint32_t read_offset =lens[i] - (rand() % (lens[i] / 2));
        PT_DEBUG(DATA, "lens[i]=%u read_offset=%u", lens[i], read_offset);
        res = ingest.read(nullptr, nullptr, handle, offset + read_offset, lens[i] - read_offset, &iovecs, &alloc_vecs,
                          &bytes_read, &eof, nullptr, nullptr);
        ASSERT(res == OK);
        ASSERT_EQ(lens[i] - read_offset, bytes_read);
        if (i != N_WRITES - 1) {
            ASSERT_FALSE(eof);
        } else {
            ASSERT_TRUE(eof);
        }
        if (bytes_read > 0) {
            LOOP(iovecs.count, j) {
                LOOP(iovecs.iovecs[j].iov_len, k) {
                    if ((char)(i + 1) != ((char *)(iovecs.iovecs[j].iov_base))[k]) {
                        printf("i=%lu j=%lu k=%lu val=%hhu\n", i, j, k, ((char *)(iovecs.iovecs[j].iov_base))[k]);
                        PANIC("data cmp failure");
                    }
                }
            }
            ingest.free_data_buffers(&alloc_vecs);
        }

        offset += lens[i];
    }
    eio.destroy();
}

int main(int argc, char **argv)
{
    Test::init_traces();
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
