/* Copyright (C) Vast Data Ltd. */
#include "io_provider.hpp"
#include "globals.hpp"
#include "plasma/fiber/fiber.hpp"

namespace P {
namespace IO {

void IOProvider::init(size_t device_count, size_t concurrent_ios)
{
    _device_count = device_count;
    _devices = new DevIO[device_count];
    _fiber = nullptr;
    _was_suspended = false;

    _active_devices_anchor.init();
    _idle_devices_anchor.init();
    _free_devices_anchor.init();
    _device_pool.init((Index)device_count);
    _active_devices.init(&_active_devices_anchor, &_device_pool);
    _idle_devices.init(&_idle_devices_anchor, &_device_pool);
    _free_devices.init(&_free_devices_anchor, &_device_pool);

    _iopool.init(concurrent_ios);

    LOOP(device_count, i) {
        _free_devices.append(i);
    }
}

DevIO *IOProvider::alloc_device(const char dev_name[], uint32_t iodepth, size_t device_size)
{
    Index index = _free_devices.pop();
    //TODO: return an enum error code
    if (index == INVALID_INDEX)
        return nullptr;
    DevIO *device = &_devices[index];
    if (!device->init(dev_name, iodepth, &_iopool, device_size)) {
        _free_devices.append(index);
        return nullptr;
    }
    _idle_devices.append(index);
    device->set_ioprovider(this);
    return device;
}

void IOProvider::free_device(DevIO *device)
{
    device->destroy();
    Index index = PTR2IDX(device, _devices);
    if (device->has_pending_ios())
        _active_devices.remove(index);
    else
        _idle_devices.remove(index);
    _free_devices.insert(index);
}

static void io_poll_fiber(void *io_provider)
{
    IOProvider *p_io_provider = (IOProvider *) io_provider;
    p_io_provider->suspend();
    DEBUG_ASSERT(p_io_provider->test_and_reset_was_suspended());
    while (true) {
        p_io_provider->poll();
        // Don't yield if we were suspended - this will waste one cycle of iterating over the fiber groups.
        if (!p_io_provider->test_and_reset_was_suspended()) {
            Fiber::yield();
        }
        if (unlikely(env_stop)) {
            break;
        }
    }
}

void IOProvider::start(FiberGroupId fiber_group)
{
    // Running this fiber as a daemon because it's suspended as long as there are no active devices
    _fiber = Fiber::init((Index)fiber_group, io_poll_fiber, this, false, true);
    ASSERT_NOT_NULL(_fiber);
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
    bool should_resume = _active_devices.is_empty();
    _idle_devices.remove(index);
    _active_devices.append(index);
    if (should_resume) {
        DEBUG_ASSERT(_was_suspended);
        _fiber->resume();
    }
}

void IOProvider::disable_polling(DevIO *device)
{
    Index index = PTR2IDX(device, _devices);
    _active_devices.remove(index);
    _idle_devices.append(index);
    if (_active_devices.is_empty()) {
        suspend();
    }
}

void IOProvider::destroy()
{
    ITER_SAFE_EACH(&_idle_devices, index,
        _devices[index].destroy();
    )
    ITER_SAFE_EACH(&_active_devices, index,
        _devices[index].destroy();
    )
    _device_pool.destroy();
}

void IOProvider::suspend()
{
    DEBUG_ASSERT(Fiber::get_current() == _fiber);  // Make sure this is called in the context of the provider fiber.
    DEBUG_ASSERT(_was_suspended == false);
    _was_suspended = true;
    Fiber::suspend();
}

}   // namespace IO
}   // namespace P
