/* Copyright (C) Vast Data Ltd. */
#pragma once

#include "plasma/io/io_provider.hpp"

namespace Test {

void create_file(const char *path, size_t size);

class IOHelper {
public:
    void init(const char *config_path);

    void destroy()
    {
        _io_provider.destroy();
    }

    P::IO::DevIO *get_device(size_t index)
    {
        return _devices[index];
    }

    size_t get_device_count() { return _device_count; }

private:
    P::IO::IOProvider _io_provider;
    P::IO::DevIO **_devices;
    size_t _device_count;
};

}
