/* Copyright (C) Vast Data Ltd. */

#include "tracker.hpp"
#include "object.hpp"
#include "plasma/internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/vmsg/vmsg_defs.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/control/agent.hpp"

namespace P { namespace Metrics {

void Tracker::init()
{
    _update_generation = 0;
    _delete_generation = 0;
    _list.init();
}

void Tracker::destroy()
{

}

IList *Tracker::get_list()
{
    return &_list;
}

/*!
 * Objects are always added to the end of the list. That way, there are higher chances
 * clients will get them on the first sync they do.
 */
void Tracker::on_object_init(Object *object)
{
    _list.append(&object->list_node);
}

void Tracker::on_object_destroy(Object *object)
{
    _delete_log[_delete_generation++ % DELETED_OBJECTS_LOG_SIZE] = object;
    object->list_node.remove();
}

void Tracker::get_generations(GetGenerationsParams *params, GetGenerationsResult *result)
{
    result->update_generation = _update_generation;
    result->delete_generation = _delete_generation;
}

/*!
 * This function returns all modified objects up to a given message size.
 * If all objects don't fit in a single RPC call, consecutive calls should be made.
 * The first call can pass a from_generation of 0 in order to get all objects.
 */
void Tracker::get_modified(GetModifiedParams *params, GetModifiedResult *result, uint16_t *res_len)
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
    result->cookie = nullptr; // assume no additional calls are needed

    IList::Node *node = (IList::Node*) params->cookie;
    if (node == nullptr)
        node = _list.get_first();

    size_t size_left = VMsg::RPC_BUFFER_SIZE - sizeof(GetModifiedResult);
    byte *write_ptr = result->data;
    ILIST_ITER_FROM(&_list, i, node) {
        Object *obj = p_container_of(i, Object, list_node);
        size_t object_size = obj->get_clone_size();
        ASSERT_OP(object_size, <=, VMsg::RPC_BUFFER_SIZE - sizeof(GetModifiedResult));
        if (object_size > size_left) { // additional calls are needed!
            PT_INFO("Next object to sync from: %p", obj);
            result->cookie = i;
            break;
        }
        if (obj->get_generation() >= params->from_generation) { // object modified!
            size_t cloned_size = obj->clone(write_ptr);
            ASSERT_EQUAL(cloned_size, object_size);
            size_left -= object_size;
            write_ptr += object_size;
            result->count++;
        }
    }
    *res_len = (uintptr_t) write_ptr - (uintptr_t) result;
}

void Tracker::get_deletions(GetDeletionsParams *params, GetDeletionsResult *result, uint16_t *res_len)
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

Tracker *Tracker::get_current()
{
    return &Silo::get_module()->control_agent->metrics_agent.tracker;
}

}}
