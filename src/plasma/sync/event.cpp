#include "event.hpp"
#include "../data/dlist.hpp"
#include "../utils/assert.hpp"
#include "../fiber/fiber.hpp"

namespace P {

namespace Sync {

void Event::init()
{
    _wait_anchor.init();
    _state = State::CLEARED;
}

void Event::destroy()
{
    ASSERT(_wait_anchor.is_empty());
}

void Event::wait()
{
    if (_state == State::SET) {
        ASSERT(_wait_anchor.is_empty());
        return;
    }
    Fiber::suspend_and_queue(&_wait_anchor);
}

void Event::set()
{
    release_all();
    _state = State::SET;
}

void Event::clear()
{
    ASSERT(_state == State::SET);
    _state = State::CLEARED;
}

void Event::release_one()
{
    ASSERT(_state == State::CLEARED);
    Fiber::pop_and_resume(&_wait_anchor);
}

void Event::release_all()
{
    ASSERT(_state == State::CLEARED);
    Fiber *fiber;
    do {
        fiber = Fiber::pop_and_resume(&_wait_anchor);
    } while(fiber != nullptr);
}

}
}
