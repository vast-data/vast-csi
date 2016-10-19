#include <gtest/gtest.h>
#include <string.h>
#include "estore/ingest.hpp"
#include "plasma/utils/assert.hpp"
#include "estore/metadata/handles_table.hpp"
#include "utils.hpp"
#include "globals.hpp"

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

class IngestTest : public ::testing::Test {
public:
    IngestTest() {
        eio.init(0, ModuleId::I, FiberGroupId::I_CONTROL, nullptr);
        eio.get_section_allocator()->do_activate(32, 16);
        shard_md.init(&eio);
        shard_md.create();

        handles_table.init(&eio, &shard_md);
        EStoreRes res = handles_table.create();
        ASSERT(res == OK);

        ingest.init(&eio, &shard_md, &handles_table);

        res = ingest.create_root();
        ASSERT(res == OK);
    }

    ~IngestTest() {
        eio.destroy();
    }


public:
    EStoreIO eio;
    ShardMd shard_md;
    HandlesTable handles_table;
    Ingest ingest;
};


TEST_F(IngestTest, test_list)
{
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
        EStoreRes res = ingest.create(nullptr, nullptr, ROOT_HANDLE, name, CreateFlags::HAS_CHILDREN, 0, &sattr, nullptr,
                                      nullptr, &handle, &handle_attr, &parent_pre_attr, &parent_post_attr);
        ASSERT(res == OK);
    }

    uint64_t n_files = 0;
    uint64_t curr_version = 0;
    EStoreRes res = ingest.list_elements(nullptr, nullptr, ROOT_HANDLE, 0, 0, list_callback, &n_files, nullptr, 0,
                                         &curr_version, nullptr);
    ASSERT(res == OK);
    ASSERT_EQ(n_files, N_FILES);
}

TEST_F(IngestTest, test_create)
{
    SettableAttr sattr;
    sattr.mode = 0444;
    sattr.flags = MODE;

    SystemAttr handle_attr;
    SystemAttr parent_pre_attr;
    SystemAttr parent_post_attr;
    EHandle handle;
    EStoreRes res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "baba", CreateFlags::HAS_CHILDREN, 0, &sattr, nullptr,
                                  nullptr, &handle, &handle_attr, &parent_pre_attr, &parent_post_attr);
    ASSERT(res == OK);
    ASSERT_EQ(handle_attr.mode, sattr.mode);
    ASSERT_GT(parent_post_attr.mtime, parent_pre_attr.mtime);
    ASSERT_GT(parent_post_attr.ctime, parent_pre_attr.ctime);
    PTC_DEBUG("created handle 0x%lx", handle);

    EHandle res_handle = 0;
    SystemAttr res_attr;
    SystemAttr parent_attr;

    res = ingest.lookup(nullptr, nullptr, ROOT_HANDLE, "gaga", true, &res_handle, &res_attr, &parent_attr);
    ASSERT(res == EStoreRes::NOENT);

    res = ingest.lookup(nullptr, nullptr, ROOT_HANDLE, "baba", true, &res_handle, &res_attr, &parent_attr);
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
    res = ingest.lookup(nullptr, nullptr, ROOT_HANDLE, "gamp", true, &res_handle, &res_attr, &parent_attr);
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

    sattr.mode = 0444;
    sattr.atime = 1000;
    sattr.mtime = 2000;
    sattr.gid = 99;
    sattr.uid = 1111;
    sattr.element_flags = (uint64_t)ElementFlags::HIDDEN;
    sattr.flags = (AttrFlag)(MODE | UID | GID | ATIME | MTIME | ELEMENT_FLAGS);

    SystemAttr pre_attr;
    SystemAttr post_attr;
    res = ingest.set_attr(nullptr, nullptr, handle, &sattr, 0, nullptr, nullptr, &pre_attr, &post_attr);
    ASSERT(res == OK);
    ASSERT_EQ(sattr.mode, post_attr.mode);
    ASSERT_EQ(sattr.atime, post_attr.atime);
    ASSERT_EQ(sattr.mtime, post_attr.mtime);
    ASSERT_EQ(sattr.gid, post_attr.gid);
    ASSERT_EQ(sattr.uid, post_attr.uid);
    ASSERT_EQ(sattr.element_flags, post_attr.element_flags);

    // check ctime guard
    sattr.mode = 0445;
    sattr.flags = MODE;
    res = ingest.set_attr(nullptr, nullptr, handle, &sattr, post_attr.ctime, nullptr, nullptr, &pre_attr, &post_attr);
    ASSERT(res == OK);
    ASSERT_EQ(sattr.mode, post_attr.mode);
    res = ingest.set_attr(nullptr, nullptr, handle, &sattr, post_attr.ctime + 1, nullptr, nullptr, &pre_attr, &post_attr);
    ASSERT(res == EStoreRes::NOT_SYNC);
}

TEST_F(IngestTest, test_simple_io)
{
    SettableAttr sattr;
    sattr.flags = MODE;
    sattr.mode = 0333;
    EHandle handle;
    SystemAttr handle_attr;
    EStoreRes res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "data", CreateFlags::HAS_DATA, 0, &sattr, nullptr,
                                  nullptr, &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    PTC_DEBUG("created handle 0x%lx", handle);

    uint64_t IOVEC_SIZE = 64;
    IOVec iovec[IOVEC_SIZE];
    IOVecs iovecs;
    iovecs.iovecs = iovec;
    uint64_t offset = 0;

    #define IO_SIZE (256 * UNIT_KiB)
    uint32_t n_writes = 5000;
    LOOP(n_writes, i) {
        iovecs.count = IO_SIZE / DATA_BUFFER_SIZE;
        static_assert(IO_SIZE % DATA_BUFFER_SIZE == 0, "IO_SIZE ");
        ingest.alloc_data_buffers(&iovecs);
        LOOP(iovecs.count, j) {
            memset(iovecs.iovecs[j].iov_base, i+1, DATA_BUFFER_SIZE);
            iovecs.iovecs[j].iov_len = DATA_BUFFER_SIZE;
        }
        res = ingest.write(nullptr, nullptr, handle, offset, &iovecs, nullptr, nullptr);
        ASSERT(res == OK);
        offset += IO_SIZE;

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
    uint32_t bytes_read;
    bool eof;
    offset = 0;
    LOOP(n_writes, i) {
        iovecs.iovecs = iovec;
        iovecs.count = IOVEC_SIZE;
        res = ingest.read(nullptr, nullptr, handle, offset, IO_SIZE, &iovecs, &alloc_vecs,
                          &bytes_read, &eof, nullptr, nullptr);
        ASSERT(res == OK);
        ASSERT_EQ(IO_SIZE, bytes_read);
        if (i != n_writes - 1) {
            ASSERT_FALSE(eof);
        } else {
            ASSERT_TRUE(eof);
        }
        LOOP(iovecs.count, j) {
            LOOP(iovecs.iovecs[j].iov_len, k) {
                if ((char)(i + 1) != ((char *)(iovecs.iovecs[j].iov_base))[k]) {
                    printf("i=%lu j=%lu k=%lu val=%hhu\n", i, j, k, ((char *)(iovecs.iovecs[j].iov_base))[k]);
                    PANIC("data cmp failure");
                }
            }
        }
        ingest.free_data_buffers(&alloc_vecs);
        offset += IO_SIZE;
    }
}

#define IOVEC_SIZE 128
static void verify_data(Ingest *ingest, EHandle handle, uint64_t n_writes, uint32_t *lens, uint64_t element_size)
{
    IOVec iovec[IOVEC_SIZE];
    IOVecs iovecs;
    iovecs.iovecs = iovec;

    IOVecs alloc_vecs;
    uint64_t offset = 0;
    uint32_t bytes_read;
    bool eof;
    // TODO check holes, reads should cover multiple writes, check overwrites, test vec len being too small
    // TODO check small writes vs large reads
    LOOP(n_writes, i) {
        iovecs.iovecs = iovec;
        iovecs.count = IOVEC_SIZE;
        uint32_t read_offset = lens[i] - (rand() % ((lens[i] / 2) + 1));
        PT_DEBUG(DATA, "lens[i]=%u read_offset=%u", lens[i], read_offset);
        EStoreRes res = ingest->read(nullptr, nullptr, handle, offset + read_offset, lens[i] - read_offset, &iovecs,
                                     &alloc_vecs, &bytes_read, &eof, nullptr, nullptr);
        ASSERT(res == OK);
        if (offset + read_offset > element_size) {
            break;
        }
        uint64_t expected_bytes_read = lens[i] - read_offset;
        bool expected_eof = offset + lens[i] >= element_size;
        ASSERT_EQUAL(P_MIN(expected_bytes_read, element_size - (offset + read_offset)), bytes_read);
        ASSERT(eof == expected_eof);
        if (bytes_read > 0) {
            LOOP(iovecs.count, j) {
                LOOP(iovecs.iovecs[j].iov_len, k) {
                    if ((char)(i + 1) != ((char *)(iovecs.iovecs[j].iov_base))[k]) {
                        printf("element_offset=%lu i=%lu j=%lu k=%lu val=%hhu\n",
                               offset + read_offset + (j * k), i, j, k, ((char *)(iovecs.iovecs[j].iov_base))[k]);
                        PANIC("data cmp failure");
                    }
                }
            }
            ingest->free_data_buffers(&alloc_vecs);
        }

        offset += lens[i];
    }
}

TEST_F(IngestTest, test_random_io)
{
    SettableAttr sattr;
    sattr.flags = MODE;
    sattr.mode = 0333;
    EHandle handle;
    SystemAttr handle_attr;
    EStoreRes res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "data", CreateFlags::HAS_DATA, 0, &sattr, nullptr,
                                  nullptr, &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    PTC_DEBUG("created handle 0x%lx", handle);

    #define WRITE_SIZE_FACTOR 12
    IOVec iovec[IOVEC_SIZE];
    IOVecs iovecs;
    iovecs.iovecs = iovec;
    uint64_t offset = 0;

    const uint64_t n_writes = 10000;
    uint32_t lens[n_writes];
    LOOP(n_writes, i) {
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

    const uint32_t TRUNCATE_COUNT = 10;
    LOOP(TRUNCATE_COUNT, i) {
        verify_data(&ingest, handle, n_writes, lens, handle_attr.size);

        // truncate testing
        sattr.flags = SIZE;
        if (i == TRUNCATE_COUNT - 1) {
            sattr.size = 0;
        } else {
            // TODO test util that gen a number in a range
            sattr.size = (uint64_t)((double)handle_attr.size * ((double)rand() / RAND_MAX));
        }
        res = ingest.set_attr(nullptr, nullptr, handle, &sattr, 0, nullptr, nullptr, nullptr, &handle_attr);
        ASSERT(res == OK);
    }
}

TEST_F(IngestTest, test_empty_truncate)
{
    SettableAttr sattr;
    sattr.flags = NONE;
    EHandle handle;
    SystemAttr handle_attr;
    EStoreRes res = ingest.create(nullptr, nullptr, ROOT_HANDLE, "data", CreateFlags::HAS_DATA, 0, &sattr, nullptr,
                                  nullptr, &handle, &handle_attr, nullptr, nullptr);
    ASSERT(res == OK);
    PTC_DEBUG("created handle 0x%lx", handle);

    uint64_t prev_size = 0;
    LOOP(100, i) {
        sattr.flags = SIZE;
        sattr.size = rand() % UNIT_GiB + UNIT_MiB;

        SystemAttr pre_attr;
        SystemAttr post_attr;
        res = ingest.set_attr(nullptr, nullptr, handle, &sattr, 0, nullptr, nullptr, &pre_attr, &post_attr);
        ASSERT(res == OK);
        ASSERT_EQ(prev_size, pre_attr.size);
        ASSERT_EQ(sattr.size, post_attr.size);
        prev_size = post_attr.size;

        IOVec iovec[IOVEC_SIZE];
        IOVecs iovecs;
        iovecs.iovecs = iovec;
        iovecs.count = IOVEC_SIZE;
        uint64_t offset = rand() % (sattr.size);

        IOVecs alloc_vecs;
        uint32_t bytes_read;
        bool eof;
        res = ingest.read(nullptr, nullptr, handle, offset, UNIT_MiB, &iovecs, &alloc_vecs,
                          &bytes_read, &eof, nullptr, nullptr);
        ASSERT(res == OK);
        ASSERT_EQ(bytes_read, P_MIN(UNIT_MiB, sattr.size - offset));
        LOOP(iovecs.count, j) {
            LOOP(iovecs.iovecs[j].iov_len, k) {
                if (0 != ((char *)(iovecs.iovecs[j].iov_base))[k]) {
                    printf("j=%lu k=%lu val=%hhu\n", j, k, ((char *)(iovecs.iovecs[j].iov_base))[k]);
                    PANIC("data cmp failure");
                }
            }
        }
        ingest.free_data_buffers(&alloc_vecs);
    }
}

int main(int argc, char **argv)
{
    global_test_mode = true;
    srand(time(0));
    system("rm -rf /tmp/eio_mock_data");
    Test::init_traces();
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
