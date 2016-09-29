#include "io_utils.hpp"

#include <fcntl.h>
#include <unistd.h>
#include <cstdio>

#include "plasma/utils/assert.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/execution/config_internal.hpp"
#include "test_common_scheduler.hpp"

using namespace P::Conf;

namespace Test {

void create_file(const char *path, size_t size)
{
    int fd = open(path, O_CREAT, S_IRUSR | S_IWUSR);
    ftruncate(fd, size);
    int ret = close(fd);
    ASSERT_EQUAL(0, ret);
}

void IOHelper::init(const char *config_path)
{
    Config* config = conf_init();
    int32_t ret = conf_read_file(config, config_path);
    ASSERT(ret);

    ConfigSetting *io_module = conf_lookup(config, "io_module");

    ConfigSetting *iopool_count_setting = conf_setting_lookup_required(io_module, "io_pool_count");
    size_t iopool_count = conf_setting_get_int32(iopool_count_setting);

    ConfigSetting *io_provider_setting = conf_setting_lookup_required(io_module, "io_provider");
    ConfigSetting *devices_setting = conf_setting_lookup_required(io_provider_setting, "devices");
    _device_count = (size_t)conf_setting_length(devices_setting);

    _devices = new P::IO::DevIO*[iopool_count];
    _io_provider.init(_device_count, iopool_count);

    LOOP(_device_count, i) {
        ConfigSetting *device_setting = conf_setting_get_element(devices_setting, (uint32_t) i);
        ConfigSetting *dev_path_setting = conf_setting_lookup_required(device_setting, "dev_path");
        ConfigSetting *io_depth_setting = conf_setting_lookup_required(device_setting, "io_depth");
        ConfigSetting *device_size_setting = conf_setting_lookup_required(device_setting, "device_size");
        const char *device_path = conf_setting_get_string(dev_path_setting);
        uint32_t io_depth = (uint32_t) conf_setting_get_int32(io_depth_setting);
        size_t device_size = (size_t) conf_setting_get_int32(device_size_setting);
        create_file(device_path, device_size);
        _devices[i] = _io_provider.alloc_device(device_path, io_depth, device_size);
    }

    conf_destroy(config);

    _io_provider.start((FiberGroupId)FG_A);
}

}
