#include "qlock.hpp"
#include "../utils/assert.hpp"

namespace P {

namespace Sync {

void Qlock::init()
{
    _anchor.init();
    _owner = NULL;
}

bool Qlock::is_locked()
{
    return _owner != NULL;
}

void Qlock::lock()
{
    if (is_locked()) {
        ASSERT(_owner != Fiber::get_current());
        Fiber::suspend_and_queue(&_anchor);
    }
    _owner = Fiber::get_current();
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
    ASSERT(_owner == Fiber::get_current());
    _owner = NULL;
    Fiber::pop_and_resume(&_anchor);
}

void Qlock::destroy()
{
    ASSERT(!is_locked());
}

}
}
