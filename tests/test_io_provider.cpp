/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "../src/globals.hpp"
#include "../src/modules/e_module.hpp"
#include "../src/plasma/execution/config_internal.hpp"
#include "../src/plasma/fiber/scheduler.hpp"
#include "../src/plasma/utils/macros.hpp"
#include "../src/plasma/io/io_provider.hpp"
#include "../src/plasma/execution/config.hpp"
#include "../src/plasma/memory/atomic_pool.hpp"
#include "../src/plasma/memory/alloc.hpp"

#include "test_common_scheduler.hpp"
#include "test_common_io.hpp"

using namespace P::Conf;
using namespace P::IO;

static void generate_scatters(IOVec write_buffers[] OUT, size_t buffer_count, IOVecs scatter[] OUT, uint32_t scatter_sizes[], size_t scatter_count,
                              const size_t buff_len, IOVecs* scatter_per_io[] OUT, uint32_t io_batches[], size_t io_submission_count)
{
    LOOP(buffer_count, i) {
        write_buffers[i].iov_base = P::aligned_new_arr<P::byte>(P::IO::DevIO::O_DIRECT_ALIGNMENT, buff_len);
        write_buffers[i].iov_len = buff_len;
    }
    // initialize scatters (pointing at the buffers)
    P::IO::IOVec* buff_ptr = write_buffers;
    LOOP(scatter_count, i)
    {
        scatter[i].count = scatter_sizes[i];
        scatter[i].iovecs = buff_ptr;

        buff_ptr += scatter[i].count;
    }
    P::IO::IOVecs* scatter_ptr = scatter;
    LOOP(io_submission_count, i)
    {
        scatter_per_io[i] = scatter_ptr;
        scatter_ptr += io_batches[i];
    }
}

static void generate_baddrs(Baddr baddrs[] OUT, uint32_t scatter_sizes[], size_t scatter_count, const size_t buff_len,
        Baddrs target_baddrs[] OUT, uint32_t io_batches[], size_t io_submission_count)
{
    // initialize target baddrs
    Baddr baddr = 0;
    LOOP(scatter_count, i)
    {
        baddrs[i] = baddr;
        // assuming all buffers are of the same size
        baddr += scatter_sizes[i] * buff_len;
    }
    // initialize target_baddrs according to amount of io submission batches.
    Baddr* baddr_ptr = baddrs;
    LOOP(io_submission_count, i)
    {
        target_baddrs[i].count = io_batches[i];
        target_baddrs[i].baddrs = baddr_ptr;
        baddr_ptr += target_baddrs[i].count;
    }
}

static void multiple_async_rw(DevIO *device)
{
    uint32_t scatter_sizes[] = {3 , 1, 5};
    uint32_t io_batches[] = {2, 1}; // this should sum up to NUM_ELEMENTS(scatter_sizes) - asserted later on

    static const size_t buff_len = DevIO::O_DIRECT_ALIGNMENT;

    size_t buffer_count = 0;
    size_t scatter_count = NUM_ELEMENTS(scatter_sizes);
    static const size_t io_submission_count = NUM_ELEMENTS(io_batches);

    // check io_batches holds valid values
    uint32_t scatter_count_from_batches = 0;
    LOOP(io_submission_count, i) {
        scatter_count_from_batches += io_batches[i];
    }
    ASSERT_EQ(scatter_count_from_batches, scatter_count);

    // count buffers
    LOOP(scatter_count, i) {
        buffer_count += scatter_sizes[i];
    }

    // initialize write buffers scatter
    IOVec write_buffers[buffer_count];
    IOVecs write_scatter[scatter_count];
    IOVecs *write_scatter_per_io[io_submission_count];
    generate_scatters(write_buffers, buffer_count, write_scatter, scatter_sizes, scatter_count,
                      buff_len, write_scatter_per_io, io_batches, io_submission_count);

    // initialize read buffers scatter
    IOVec read_buffers[buffer_count];
    IOVecs read_scatter[scatter_count];
    IOVecs *read_scatter_per_io[io_submission_count];
    generate_scatters(read_buffers, buffer_count, read_scatter, scatter_sizes, scatter_count,
                      buff_len, read_scatter_per_io, io_batches, io_submission_count);

    // set some content in write buffers
    LOOP(buffer_count, i) {
        memset(write_buffers[i].iov_base, (int)i, write_buffers[i].iov_len);
    }

    // initialize  baddrs
    Baddr baddrs[scatter_count];
    Baddrs io_submission_baddrs[io_submission_count];
    generate_baddrs(baddrs, scatter_sizes, scatter_count, buff_len, io_submission_baddrs, io_batches, io_submission_count);

    // submit all write ios
    BaseIO::Future write_futures[io_submission_count];
    bool io_ret;
    LOOP(io_submission_count, i) {
//        printf("sumitting write to %u addresses:\n", io_submission_baddrs[i].count);
//        LOOP(io_submission_baddrs[i].count, j) {
//            printf("%lu: scatter of %u buffers\n", j, write_scatter_per_io[i][j].count);
//        }
        io_ret = device->write_scatter(write_scatter_per_io[i], &io_submission_baddrs[i], &write_futures[i]);
        ASSERT_TRUE(io_ret);
    }

    // wait & read every io
    DevIO::Future read_futures[io_submission_count];
    LOOP(io_submission_count, i) {
        io_ret = device->wait(&write_futures[i]);
        ASSERT_TRUE(io_ret);
        ASSERT_TRUE(write_futures[i].res);

//        printf("sumitting read to %u addresses:\n", io_submission_baddrs[i].count);
//        LOOP(io_submission_baddrs[i].count, j) {
//            printf("%lu: scatter of %u buffers\n", j, read_scatter_per_io[i][j].count);
//        }

        io_ret = device->read_scatter(read_scatter_per_io[i], &io_submission_baddrs[i], &read_futures[i]);
        ASSERT_TRUE(io_ret);
    }

    // wait for all read operations
    LOOP(io_submission_count, i) {
        io_ret = device->wait(&read_futures[i]);
        ASSERT_TRUE(io_ret);
        ASSERT_TRUE(read_futures[i].res);
    }

    // once this is operational- uncomment
//    p_devio_trim(device, 0, buffer_count * buff_len);
//    p_devio_flush(device);

    LOOP(buffer_count, i) {
        ASSERT_EQ(0, memcmp(write_buffers[i].iov_base, read_buffers[i].iov_base, buff_len));
        P::aligned_delete(write_buffers[i].iov_base);
        P::aligned_delete(read_buffers[i].iov_base);
    }
}

static void simple_rw(DevIO *device)
{
    char data[] = "Avi Nimni is the king";

    static const size_t buff_len = DevIO::O_DIRECT_ALIGNMENT;

    char* write_buffer = P::aligned_new_arr<char>(DevIO::O_DIRECT_ALIGNMENT, buff_len);

    strncpy(write_buffer, data, sizeof(data));

    IOVec io;
    io.iov_base = write_buffer;
    io.iov_len = buff_len;

    bool io_ret = device->write(&io, 0, nullptr);
    ASSERT_TRUE(io_ret);

    char* read_buffer = P::aligned_new_arr<char>(DevIO::O_DIRECT_ALIGNMENT, buff_len);

    io.iov_base = read_buffer;
    io.iov_len = buff_len;

    io_ret = device->read(&io, 0, nullptr);
    ASSERT_TRUE(io_ret);

    size_t len = strnlen(read_buffer, buff_len);
    ASSERT_LT(len, sizeof(data));

//    printf("Read \"%s\" from device!\n", read_buffer);

    int ret = strncmp(write_buffer, read_buffer, buff_len);
    ASSERT_EQ(ret, 0);

    P::aligned_delete(write_buffer);
    P::aligned_delete(read_buffer);
}

static void io_submitter(void *arg)
{
    DevIO *device = (DevIO*) arg;

    simple_rw(device);

    multiple_async_rw(device);

    env_stop = true;
}

TEST(TestIOProvider, test)
{
    Config* config = conf_init();

    int32_t ret = conf_read_file(config, "tests/test_io_provider.config");
    ASSERT_TRUE(ret);

    ConfigSetting *io_module = conf_lookup(config, "io_module");

    devices_test_files(io_module, true);

    DevIO *devices;
    P::AtomicPool<DevIO::IO> iopool;

    IOProvider io_provider;

    P::EModule::init_io_from_settings(io_module, &devices, &iopool, &io_provider);

    P::Scheduler::init(&scheduler_config);

    io_provider.start();
    P::Fiber::init(FG_A, io_submitter, &devices[0], false);

    P::Scheduler::run();

    devices_test_files(io_module, false);

    P::Scheduler::destroy();

    io_provider.destroy();
    iopool.destroy();
    delete[] devices;

    conf_destroy(config);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
