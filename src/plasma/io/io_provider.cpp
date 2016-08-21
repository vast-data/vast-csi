/* Copyright (C) Vast Data Ltd. */
#include "io_provider.hpp"
#include "globals.hpp"
#include "plasma/fiber/fiber.hpp"

namespace P {

void IOProvider::init(DevIO devices[], size_t device_count)
{
    _device_count = device_count;
    _devices = devices;
    _fiber = nullptr;
    _was_suspended = false;

    _active_devices_anchor.init();
    _active_devices_pool.init((Index)device_count);
    _active_devices.init(&_active_devices_anchor, & _active_devices_pool);

    LOOP(device_count, i) {
        _devices[i].set_ioprovider(this);
    }
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

void IOProvider::start()
{
    // Running this fiber as a daemon because it's suspended as long as there are no active devices
    _fiber = Fiber::init((Index)FiberGroupId::P_IO_POLLING, io_poll_fiber, this, false, true);
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
    if (_active_devices.is_empty()) {
        suspend();
    }
}

void IOProvider::destroy()
{
    _active_devices.destroy();
    _active_devices_pool.destroy();
    LOOP_TYPE(Index, _device_count, index) {
        _devices[index].destroy();
    }
}

void IOProvider::suspend()
{
    DEBUG_ASSERT(Fiber::get_current() == _fiber);  // Make sure this is called in the context of the provider fiber.
    DEBUG_ASSERT(_was_suspended == false);
    _was_suspended = true;
    Fiber::suspend();
}

}  // namespace P
