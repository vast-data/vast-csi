/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <setjmp.h>
#include <cmocka.h>

#include "../src/plasma/execution/p_config_internal.h"

#include <fcntl.h>
#include <unistd.h>

static bool testing = true;

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

static void generate_scatters(IOVec write_buffers[] OUT, size_t buffer_count, IOVecs scatter[] OUT, uint32_t scatter_sizes[], size_t scatter_count,
                              const size_t buff_len, IOVecs* scatter_per_io[] OUT, uint32_t io_batches[], size_t io_submission_count)
{
    LOOP(buffer_count, i) {
        write_buffers[i].iov_base = aligned_alloc(O_DIRECT_ALIGN, buff_len);
        write_buffers[i].iov_len = buff_len;
    }
    // initialize scatters (pointing at the buffers)
    IOVec* buff_ptr = write_buffers;
    LOOP(scatter_count, i)
    {
        scatter[i].count = scatter_sizes[i];
        scatter[i].iovecs = buff_ptr;

        buff_ptr += scatter[i].count;
    }
    IOVecs* scatter_ptr = scatter;
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

static void multiple_async_rw(PDevIO *device)
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
    assert_true(scatter_count_from_batches == scatter_count);

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
    PDevIOFuture write_futures[io_submission_count];
    IODevRet io_ret;
    LOOP(io_submission_count, i) {
//        printf("sumitting write to %u addresses:\n", io_submission_baddrs[i].count);
//        LOOP(io_submission_baddrs[i].count, j) {
//            printf("%lu: scatter of %u buffers\n", j, write_scatter_per_io[i][j].count);
//        }
        io_ret = p_devio_write_scatter(device, write_scatter_per_io[i], &io_submission_baddrs[i], &write_futures[i]);
        assert_true(io_ret == P_IODEV_SUCCESS);
    }

    // wait & read every io
    PDevIOFuture read_futures[io_submission_count];
    LOOP(io_submission_count, i) {
        io_ret = p_devio_wait(device, &write_futures[i]);
        assert_true(io_ret == P_IODEV_SUCCESS);

//        printf("sumitting read to %u addresses:\n", io_submission_baddrs[i].count);
//        LOOP(io_submission_baddrs[i].count, j) {
//            printf("%lu: scatter of %u buffers\n", j, read_scatter_per_io[i][j].count);
//        }

        io_ret = p_devio_read_scatter(device, read_scatter_per_io[i], &io_submission_baddrs[i], &read_futures[i]);
        assert_true(io_ret == P_IODEV_SUCCESS);
    }

    // wait for all read operations
    LOOP(io_submission_count, i) {
        io_ret = p_devio_wait(device, &read_futures[i]);
        assert_true(io_ret == P_IODEV_SUCCESS);
    }

    // once this is operational- uncomment
//    p_devio_trim(device, 0, buffer_count * buff_len);
//    p_devio_flush(device);

    LOOP(buffer_count, i) {
        assert_true(0 == memcmp(write_buffers[i].iov_base, read_buffers[i].iov_base, buff_len));
        free(write_buffers[i].iov_base);
        free(read_buffers[i].iov_base);
    }
}

static void simple_rw(PDevIO *device)
{
    char data[] = "Avi Nimni is the king";

    static const size_t buff_len = O_DIRECT_ALIGN;
    char* write_buffer = aligned_alloc(O_DIRECT_ALIGN, buff_len);

    strncpy(write_buffer, data, sizeof(data));

    IOVec io;
    io.iov_base = write_buffer;
    io.iov_len = buff_len;

    IODevRet io_ret = p_devio_write(device, &io, 0, NULL);
    assert_true(io_ret == P_IODEV_SUCCESS);

    char* read_buffer = aligned_alloc(O_DIRECT_ALIGN, buff_len);

    io.iov_base = read_buffer;
    io.iov_len = buff_len;

    io_ret = p_devio_read(device, &io, 0, NULL);
    assert_true(io_ret == P_IODEV_SUCCESS);

    size_t len = strnlen(read_buffer, buff_len);
    assert_true(len < sizeof(data));

//    printf("Read \"%s\" from device!\n", read_buffer);

    int ret = strncmp(write_buffer, read_buffer, buff_len);
    assert_true(ret == 0);

    free(write_buffer);
    free(read_buffer);
}

static void io_submitter(void *arg)
{
    PIOProvider *io_provider = (PIOProvider*) arg;

    PDevIO *device = &io_provider->devices[0];

    simple_rw(device);

    multiple_async_rw(device);

    testing = false;
}

static void io_poller(void *arg)
{
    PIOProvider *io_provider = (PIOProvider*) arg;
    while (testing) {
        p_io_provider_poll(io_provider);
        p_fiber_yield();
    }
}

static const char *create_device_file(PConfigSetting *io_module)
{
    PConfigSetting *io_provider_setting = p_config_setting_lookup_required(io_module, "io_provider");
    PConfigSetting *devices_setting = p_config_setting_lookup_required(io_provider_setting, "devices");

    assert_true(p_config_setting_length(devices_setting) == 1);

    PConfigSetting *device_setting = p_config_setting_get_element(devices_setting, 0);
    PConfigSetting *dev_path_setting = p_config_setting_lookup_required(device_setting, "dev_path");
    const char *dev_path = p_config_setting_get_string(dev_path_setting);

    int fd = open(dev_path,  O_CREAT, S_IRUSR | S_IWUSR);

    ftruncate(fd, DEVICE_FILE_SIZE);

    int ret = close(fd);
    assert_true(ret == 0);

    return dev_path;
}

static void test_io_provider(void **state UNUSED)
{
    PConfig config;

    p_config_init(&config);

    int32_t ret = p_config_read_file(&config, "tests/test_io_provider.config");
    assert_true(ret != CONFIG_FALSE);

    PConfigSetting *io_module = p_config_lookup(&config, "io_module");

    const char *dev_path = create_device_file(io_module);

    PIOProvider *io_provider = p_io_provider_init_from_settings(io_module);

    p_scheduler_init(&scheduler_config);

    p_fiber_init(FG_A, io_poller, io_provider, false);

    p_fiber_init(FG_A, io_submitter, io_provider, false);

    p_scheduler_run();

    remove(dev_path);

    p_scheduler_destroy();

    p_config_destroy(&config);
}

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_io_provider)
    };
    return cmocka_run_group_tests(tests, NULL, NULL);
}
