/* Copyright (C) Vast Data Ltd. */
#include "io_provider.hpp"

namespace P {

void IOProvider::init(DevIO devices[], size_t device_count)
{
    _device_count = device_count;
    _devices = devices;

    _active_devices_anchor.init();
    _active_devices_pool.init((Index)device_count);
    _active_devices.init(&_active_devices_anchor, & _active_devices_pool);

    LOOP(device_count, i) {
        _devices[i].set_ioprovider(this);
    }
}

void IOProvider::poll()
{
    ITER_SAFE_EACH(&_active_devices, index,
        _devices[index].poll_events();
    )
}

void IOProvider::enable_polling(DevIO *device)
{
    Index index = PTR2IDX(device, _devices);
    _active_devices.append(index);
}

void IOProvider::disable_polling(DevIO *device)
{
    Index index = PTR2IDX(device, _devices);
    _active_devices.remove(index);
}

void IOProvider::destroy()
{
    _active_devices.destroy();
    _active_devices_pool.destroy();
    LOOP_TYPE(Index, _device_count, index) {
        _devices[index].destroy();
    }
}

}
