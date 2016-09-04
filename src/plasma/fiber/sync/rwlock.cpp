#include "rwlock.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/fiber/fiber.hpp"

namespace P {

namespace FiberSync {

void RWlock::init()
{
    _writer = nullptr;
    _wait_anchor.init();
    _read_count = 0;
    _state = Type::FREE;
}

void RWlock::destroy()
{
    ASSERT(_writer == nullptr);
    ASSERT(_read_count == 0);
    ASSERT(_state == Type::FREE);
    ASSERT(_wait_anchor.is_empty());
}

void RWlock::lock_read()
{
    auto suspend_state = Fiber::get_current()->get_suspend_state();
    suspend_state->rw_lock_type = Type::READ;

    switch(_state) {
    case Type::FREE:
        ASSERT(_read_count == 0);
        ASSERT(_writer == nullptr);
        _state = Type::READ;
        _read_count++;
        break;
    case Type::READ:
        ASSERT(_read_count > 0);
        // if there are waiters, there's a writer before us and we should suspend
        if (!_wait_anchor.is_empty()) {
            Fiber::suspend_and_queue(&_wait_anchor);
        } else { // otherwise, we join the current readers
            _read_count++;
        }
        break;
    case Type::WRITE:
        Fiber::suspend_and_queue(&_wait_anchor);
        break;
    }
}

void RWlock::lock_write()
{
    auto fiber = Fiber::get_current();
    auto suspend_state = fiber->get_suspend_state();
    suspend_state->rw_lock_type = Type::WRITE;

    switch(_state) {
    case Type::FREE:
        ASSERT(_read_count == 0);
        ASSERT(_writer == nullptr);
        _state = Type::WRITE;
        _writer = fiber;
        break;
    case Type::READ:
        ASSERT(_read_count > 0);
        Fiber::suspend_and_queue(&_wait_anchor);
        break;
    case Type::WRITE:
        Fiber::suspend_and_queue(&_wait_anchor);
        break;
    }
}

void RWlock::unlock()
{
    switch(_state) {
    case Type::FREE:
        PANIC();
    case Type::READ:
        ASSERT(_read_count > 0);
        _read_count--;
        if (_read_count == 0)
            _state = Type::FREE;
        break;
    case Type::WRITE:
        ASSERT(_writer == Fiber::get_current());
        _writer = nullptr;
        _state = Type::FREE;
        break;
    }

    // give the lock to the next pending fiber
    if (_state == Type::FREE) {
        do {
            auto fiber = Fiber::queue_peek(&_wait_anchor);
            if (fiber == nullptr)
                break;
            auto suspend_state = fiber->get_suspend_state();
            if (suspend_state->rw_lock_type == Type::WRITE) {
                // already locked for read
                if (_state == Type::READ) {
                    break;
                } else { // lock is free. lock and return
                    _state = Type::WRITE;
                    _writer = fiber;
                    Fiber::pop_and_resume(&_wait_anchor);
                    break;
                }
            } else { // add a reader
                _state = Type::READ;
                _read_count++;
                Fiber::pop_and_resume(&_wait_anchor);
            }
        } while(true);
    }
}

}
}
