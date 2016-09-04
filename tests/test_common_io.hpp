/* Copyright (C) Vast Data Ltd. */

/*!
 * \file test_common_io.hpp
 * \brief A collection of useful IO related definitions for tests
 */

#pragma once

#include "plasma/execution/config_internal.hpp"
#include <fcntl.h>

using namespace P::Conf;

const size_t g_test_device_file_size = (20<<10); // 20K

inline bool
file_exists(const char* path)
{
  struct stat dummy_stat;
  return (stat (path, &dummy_stat) == 0);
}

// when create=true Ensures existence of device files. otherwise removes them.
void devices_test_files(ConfigSetting *io_module, bool create)
{
    ConfigSetting *devices_setting = conf_setting_lookup_required(io_module, "io_provider.devices");
    size_t device_count = conf_setting_length(devices_setting);
    LOOP(device_count, i) {
        ConfigSetting *device_setting = conf_setting_get_element(devices_setting, i);
        ConfigSetting *dev_path_setting = conf_setting_lookup_required(device_setting, "dev_path");
        const char *dev_path = conf_setting_get_string(dev_path_setting);

        if (create) {
            if (!file_exists(dev_path)) {
                int fd = open(dev_path,  O_CREAT, S_IRUSR | S_IWUSR);

                ftruncate(fd, g_test_device_file_size);

                int ret = close(fd);
                EXPECT_EQ(0, ret);
            }
        } else {
            int ret = remove(dev_path);
            EXPECT_TRUE((ret == 0) || (ret == -ENOENT));
        }
    }
}
