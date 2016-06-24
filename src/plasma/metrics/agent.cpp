/* Copyright (C) Vast Data Ltd. */

#include "agent.hpp"
#include "object.hpp"
#include "plasma/internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/vmsg/vmsg_defs.hpp"

namespace P { namespace Metrics {

void Agent::init()
{
    _update_generation = 0;
    _delete_generation = 0;
    _head = nullptr;
    _tail = nullptr;
}

void Agent::destroy()
{

}

void Agent::on_object_init(Object *object)
{
    if (unlikely(_head == nullptr)) {
        _head = object;
        _tail = object;
    } else {
        _tail->set_next(object);
        _tail = object;
    }
}

void Agent::on_object_destroy(Object *object)
{
    _delete_log[_delete_generation++ % DELETED_OBJECTS_LOG_SIZE] = object;

    if (unlikely(object == _tail && object == _head)) {
        _tail = nullptr;
        _head = nullptr;
        return;
    }

    if (likely(object != _head)) {
        Object *prev = _head;
        while (prev->get_next() != object) {
            prev = prev->get_next();
        }
        prev->set_next(object->get_next());

        if (unlikely(object == _tail))
            _tail = prev;
    } else {
        _head = object->get_next();
    }
}

void Agent::get_generations(GetGenerationsParams *params, GetGenerationsResult *result)
{
    result->update_generation = _update_generation;
    result->delete_generation = _delete_generation;
}

void Agent::get_modified(GetModifiedParams *params, GetModifiedResult *result, uint16_t *res_len)
{
    PT_INFO("Getting objects modified from generation=%ld", params->from_generation);
    *res_len = sizeof(GetModifiedResult);
    if (params->delete_generation != _delete_generation ||
        params->from_generation > _update_generation) {
        result->success = false;
        PT_INFO("Delete generation differs: %ld vs. %ld", params->delete_generation, _delete_generation);
        return;
    }
    result->success = true;
    result->count = 0;
    result->next_object = nullptr;

    Object *obj = params->from_object;
    if (obj == nullptr)
        obj = _head;

    byte *write_ptr = result->data;
    size_t size_left = VMsg::RPC_BUFFER_SIZE - sizeof(GetModifiedResult);
    while (obj != nullptr) {
        auto object_size = obj->get_clone_size();
        ASSERT_OP(object_size, <=, VMsg::RPC_BUFFER_SIZE - sizeof(GetModifiedResult));
        if (object_size > size_left) {
            result->next_object = obj;
            break;
        }
        if (obj->get_generation() >= params->from_generation) {
            ASSERT_EQUAL(obj->clone(write_ptr), object_size);
            size_left -= object_size;
            write_ptr += object_size;
            result->count++;
        }
        obj = obj->get_next();
    }
    PT_INFO("Next object to sync from: %p", obj);
    *res_len = (uintptr_t) write_ptr - (uintptr_t) result;
}

void Agent::get_deletions(GetDeletionsParams *params, GetDeletionsResult *result, uint16_t *res_len)
{
    uint64_t start_generation = params->from_generation;
    if (_delete_generation - start_generation > DELETED_OBJECTS_LOG_SIZE ||
        start_generation > _delete_generation) {
        PT_INFO("Delete generation overflow: %ld vs. %ld", params->from_generation, _delete_generation);
        result->success = false;
        return;
    }
    result->success = true;

    size_t size_left = VMsg::RPC_BUFFER_SIZE;
    size_t i = 0;
    while (start_generation < _delete_generation && size_left > sizeof(Object*)) {
        size_left -= sizeof(Object*);
        result->objects[i++] = _delete_log[(start_generation++) % DELETED_OBJECTS_LOG_SIZE];
    }
    result->count = i;
    result->has_more = start_generation < _delete_generation;
    PT_INFO("Returned %hd objects. Has more: %c", result->count, result->has_more);
    *res_len = sizeof(GetDeletionsResult) + sizeof(Object*) * i;
}

}}
