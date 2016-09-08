#include "qlock.hpp"
#include "plasma/utils/assert.hpp"

namespace P {

namespace FiberSync {

void Qlock::init()
{
    _anchor.init();
    _owner = nullptr;
}

bool Qlock::is_locked()
{
    return _owner != nullptr;
}

void Qlock::lock()
{
    if (is_locked()) {
        ASSERT(_owner != Fiber::get_current());
        Fiber::suspend_and_queue(&_anchor);
        ASSERT(_owner == Fiber::get_current());
    } else {
        _owner = Fiber::get_current();
    }
}

bool Qlock::trylock()
{
    if (is_locked())
        return false;
    lock();
    return true;
}

void Qlock::unlock()
{
    _owner = Fiber::pop_and_resume(&_anchor);
}

void Qlock::destroy()
{
    ASSERT(!is_locked());
}

}
}
