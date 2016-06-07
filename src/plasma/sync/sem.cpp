//#include "../fiber/p_scheduler_internal.h"

#include "sem.hpp"
#include "../fiber/fiber.hpp"
#include "../utils/assert.hpp"

namespace P {

namespace Sync {

void Sem::init(uint32_t value)
{
    _value = value;
    _wait_anchor.init();
}

void Sem::inc(uint32_t count)
{
    _value += count;

    do {
        auto fiber = Fiber::queue_peek(&_wait_anchor);
        if (fiber == NULL) {
            break;
        }

        auto suspend_state = fiber->get_suspend_state();
        if(_value < suspend_state->sem_count) {
            break;
        }

        _value -= suspend_state->sem_count;
        Fiber::pop_and_resume(&_wait_anchor);
    } while (true);
}

bool Sem::trydec(uint32_t count)
{
    if (_value < count)
        return false;
    dec(count);
    return true;
}

void Sem::dec(uint32_t count)
{
    if (_value < count) {
        auto suspend_state = Fiber::get_current()->get_suspend_state();
        suspend_state->sem_count = count;
        Fiber::suspend_and_queue(&_wait_anchor);
    } else {
        _value -= count;
    }
}

void Sem::destroy()
{
    ASSERT(_wait_anchor.is_empty());
}

}
}
