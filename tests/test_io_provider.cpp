/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <setjmp.h>
#include <gtest/gtest.h>

#include "../src/plasma/execution/config_internal.hpp"
#include "../src/plasma/utils/macros.hpp"
#include "../src/plasma/io/io_provider.hpp"
#include "../src/plasma/execution/config.hpp"
#include "../src/plasma/memory/atomic_pool.hpp"

#include <fcntl.h>
#include <unistd.h>

static bool testing_io_provider = true;

using namespace P::Conf;

#define DEVICE_FILE_SIZE (20<<10) // 20K

#define PAGE_SIZE 4096
static PFiberGroupConfig fiber_groups[] = {
    {.fiber_count = 0, .stack_size = 0},
    {.fiber_count = 40, .stack_size = PAGE_SIZE * 16}
};
static PSchedulerConfig scheduler_config = {
    .fiber_groups = fiber_groups, .group_count = NUM_ELEMENTS(fiber_groups)
};

enum test_fiber_group {
    FG_EMPTY,
    FG_A
};

static void generate_scatters(P::IOVec write_buffers[] OUT, size_t buffer_count, P::IOVecs scatter[] OUT, uint32_t scatter_sizes[], size_t scatter_count,
                              const size_t buff_len, P::IOVecs* scatter_per_io[] OUT, uint32_t io_batches[], size_t io_submission_count)
{
    LOOP(buffer_count, i) {
        write_buffers[i].iov_base = aligned_alloc(O_DIRECT_ALIGN, buff_len);
        write_buffers[i].iov_len = buff_len;
    }
    // initialize scatters (pointing at the buffers)
    P::IOVec* buff_ptr = write_buffers;
    LOOP(scatter_count, i)
    {
        scatter[i].count = scatter_sizes[i];
        scatter[i].iovecs = buff_ptr;

        buff_ptr += scatter[i].count;
    }
    P::IOVecs* scatter_ptr = scatter;
    LOOP(io_submission_count, i)
    {
        scatter_per_io[i] = scatter_ptr;
        scatter_ptr += io_batches[i];
    }
}

static void generate_baddrs(P::Baddr baddrs[] OUT, uint32_t scatter_sizes[], size_t scatter_count, const size_t buff_len,
        P::Baddrs target_baddrs[] OUT, uint32_t io_batches[], size_t io_submission_count)
{
    // initialize target baddrs
    P::Baddr baddr = 0;
    LOOP(scatter_count, i)
    {
        baddrs[i] = baddr;
        // assuming all buffers are of the same size
        baddr += scatter_sizes[i] * buff_len;
    }
    // initialize target_baddrs according to amount of io submission batches.
    P::Baddr* baddr_ptr = baddrs;
    LOOP(io_submission_count, i)
    {
        target_baddrs[i].count = io_batches[i];
        target_baddrs[i].baddrs = baddr_ptr;
        baddr_ptr += target_baddrs[i].count;
    }
}

static void multiple_async_rw(P::DevIO *device)
{
    uint32_t scatter_sizes[] = {3 , 1, 5};
    uint32_t io_batches[] = {2, 1}; // this should sum up to NUM_ELEMENTS(scatter_sizes) - asserted later on

    static const size_t buff_len = O_DIRECT_ALIGN;

    size_t buffer_count = 0;
    size_t scatter_count = NUM_ELEMENTS(scatter_sizes);
    size_t io_submission_count = NUM_ELEMENTS(io_batches);

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
    P::IOVec write_buffers[buffer_count];
    P::IOVecs write_scatter[scatter_count];
    P::IOVecs *write_scatter_per_io[io_submission_count];
    generate_scatters(write_buffers, buffer_count, write_scatter, scatter_sizes, scatter_count,
                      buff_len, write_scatter_per_io, io_batches, io_submission_count);

    // initialize read buffers scatter
    P::IOVec read_buffers[buffer_count];
    P::IOVecs read_scatter[scatter_count];
    P::IOVecs *read_scatter_per_io[io_submission_count];
    generate_scatters(read_buffers, buffer_count, read_scatter, scatter_sizes, scatter_count,
                      buff_len, read_scatter_per_io, io_batches, io_submission_count);

    // set some content in write buffers
    LOOP(buffer_count, i) {
        memset(write_buffers[i].iov_base, (int)i, write_buffers[i].iov_len);
    }

    // initialize  baddrs
    P::Baddr baddrs[scatter_count];
    P::Baddrs io_submission_baddrs[io_submission_count];
    generate_baddrs(baddrs, scatter_sizes, scatter_count, buff_len, io_submission_baddrs, io_batches, io_submission_count);

    // submit all write ios
    P::DevIO::Future write_futures[io_submission_count];
    P::DevIO::ReturnCode io_ret;
    LOOP(io_submission_count, i) {
//        printf("sumitting write to %u addresses:\n", io_submission_baddrs[i].count);
//        LOOP(io_submission_baddrs[i].count, j) {
//            printf("%lu: scatter of %u buffers\n", j, write_scatter_per_io[i][j].count);
//        }
        io_ret = device->write_scatter(write_scatter_per_io[i], &io_submission_baddrs[i], &write_futures[i]);
        ASSERT_EQ(io_ret, P_IODEV_SUCCESS);
    }

    // wait & read every io
    P::DevIO::Future read_futures[io_submission_count];
    LOOP(io_submission_count, i) {
        io_ret = device->wait(&write_futures[i]);
        ASSERT_EQ(io_ret, P_IODEV_SUCCESS);

//        printf("sumitting read to %u addresses:\n", io_submission_baddrs[i].count);
//        LOOP(io_submission_baddrs[i].count, j) {
//            printf("%lu: scatter of %u buffers\n", j, read_scatter_per_io[i][j].count);
//        }

        io_ret = device->read_scatter(read_scatter_per_io[i], &io_submission_baddrs[i], &read_futures[i]);
        ASSERT_EQ(io_ret, P_IODEV_SUCCESS);
    }

    // wait for all read operations
    LOOP(io_submission_count, i) {
        io_ret = device->wait(&read_futures[i]);
        ASSERT_EQ(io_ret, P_IODEV_SUCCESS);
    }

    // once this is operational- uncomment
//    p_devio_trim(device, 0, buffer_count * buff_len);
//    p_devio_flush(device);

    LOOP(buffer_count, i) {
        ASSERT_EQ(0, memcmp(write_buffers[i].iov_base, read_buffers[i].iov_base, buff_len));
        free(write_buffers[i].iov_base);
        free(read_buffers[i].iov_base);
    }
}

static void simple_rw(P::DevIO *device)
{
    char data[] = "Avi Nimni is the king";

    static const size_t buff_len = O_DIRECT_ALIGN;
    char* write_buffer = (char*)aligned_alloc(O_DIRECT_ALIGN, buff_len);

    strncpy(write_buffer, data, sizeof(data));

    P::IOVec io;
    io.iov_base = write_buffer;
    io.iov_len = buff_len;

    P::DevIO::ReturnCode io_ret = device->write(&io, 0, NULL);
    ASSERT_EQ(io_ret, P_IODEV_SUCCESS);

    char* read_buffer = (char*)aligned_alloc(O_DIRECT_ALIGN, buff_len);

    io.iov_base = read_buffer;
    io.iov_len = buff_len;

    io_ret = device->read(&io, 0, NULL);
    ASSERT_EQ(io_ret, P_IODEV_SUCCESS);

    size_t len = strnlen(read_buffer, buff_len);
    ASSERT_LT(len, sizeof(data));

//    printf("Read \"%s\" from device!\n", read_buffer);

    int ret = strncmp(write_buffer, read_buffer, buff_len);
    ASSERT_EQ(ret, 0);

    free(write_buffer);
    free(read_buffer);
}

static void io_submitter(void *arg)
{
    P::IOProvider *io_provider = (P::IOProvider*) arg;

    P::DevIO *device = &io_provider->_devices[0];

    simple_rw(device);

    multiple_async_rw(device);

    testing_io_provider = false;
}

static void io_poller(void *arg)
{
    P::IOProvider *io_provider = (P::IOProvider*) arg;
    while (testing_io_provider) {
        io_provider->poll();
        p_fiber_yield();
    }
}

static const char *create_device_file(ConfigSetting *io_module)
{
    ConfigSetting *io_provider_setting = conf_setting_lookup_required(io_module, "io_provider");
    ConfigSetting *devices_setting = conf_setting_lookup_required(io_provider_setting, "devices");

    EXPECT_EQ(1, conf_setting_length(devices_setting));

    ConfigSetting *device_setting = conf_setting_get_element(devices_setting, 0);
    ConfigSetting *dev_path_setting = conf_setting_lookup_required(device_setting, "dev_path");
    const char *dev_path = conf_setting_get_string(dev_path_setting);

    int fd = open(dev_path,  O_CREAT, S_IRUSR | S_IWUSR);

    ftruncate(fd, DEVICE_FILE_SIZE);

    int ret = close(fd);
    EXPECT_EQ(0, ret);

    return dev_path;
}

void init_from_settings(ConfigSetting *io_module, P::DevIO **devices, P::AtomicPool *iopool, P::IOProvider *io_provider)
{
    ConfigSetting* iopool_count_setting = conf_setting_lookup_required(io_module, "io_pool_count");
    PIndex iopool_count = (PIndex) conf_setting_get_int32(iopool_count_setting);
    iopool->init(iopool_count, sizeof(PIO));

    ConfigSetting *io_provider_setting = conf_setting_lookup_required(io_module, "io_provider");
    ConfigSetting *devices_setting = conf_setting_lookup_required(io_provider_setting, "devices");
    const size_t device_count = (size_t)conf_setting_length(devices_setting);
    *devices = new P::DevIO[device_count];

    LOOP(device_count, i)
    {
        ConfigSetting *device_setting = conf_setting_get_element(devices_setting, (uint32_t) i);
        ConfigSetting *dev_path_setting = conf_setting_lookup_required(device_setting, "dev_path");
        ConfigSetting *io_depth_setting = conf_setting_lookup_required(device_setting, "io_depth");
        ConfigSetting *device_size_setting = conf_setting_lookup_required(device_setting, "device_size");

        if (unlikely(!(*devices)[i].init(conf_setting_get_string(dev_path_setting),
                                      (uint32_t)conf_setting_get_int32(io_depth_setting), iopool,
                                      (size_t)conf_setting_get_int32(device_size_setting)))) {
            // Todo: this should be replaces with a notification to control and then possibly skip/retry/panic?
            P_PANIC();
        }
    }

    io_provider->init(*devices, device_count);
}


TEST(TestIOProvider, test) {
    Config* config = conf_init();

    int32_t ret = conf_read_file(config, "tests/test_io_provider.config");

    ASSERT_NE(ret, CONFIG_FALSE);

    ConfigSetting *io_module = conf_lookup(config, "io_module");

    const char *dev_path = create_device_file(io_module);

    P::DevIO *devices;
    P::AtomicPool iopool;
    P::IOProvider io_provider;

    init_from_settings(io_module, &devices, &iopool, &io_provider);

    p_scheduler_init(&scheduler_config);

    p_fiber_init(FG_A, io_poller, &io_provider, false);

    p_fiber_init(FG_A, io_submitter, &io_provider, false);

    p_scheduler_run();

    remove(dev_path);

    p_scheduler_destroy();

    io_provider.destroy();
    iopool.destroy();
    delete[] devices;

    conf_destroy(config);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
