/* Copyright (C) Vast Data Ltd. */

#include "tracker.hpp"
#include "object.hpp"
#include "control/agent.hpp"
#include "plasma/internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/vmsg/vmsg_defs.hpp"
#include "plasma/execution/silo.hpp"

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

void Tracker::get_generations(GetGenerationsParams::RootReader *params, GetGenerationsResult::RootBuilder *result)
{
    result->set_update_generation(_update_generation);
    result->set_delete_generation(_delete_generation);
}

/*!
 * This function returns all modified objects up to a given message size.
 * If all objects don't fit in a single RPC call, consecutive calls should be made.
 * The first call can pass a from_generation of 0 in order to get all objects.
 */
void Tracker::get_modified(GetModifiedParams::RootReader *params, GetModifiedResult::RootBuilder *result)
{
    PT_INFO(CONTROL, "Getting objects modified from generation=%ld", params->get_from_generation());
    if (params->get_delete_generation() != _delete_generation ||
        params->get_from_generation() > _update_generation) {
        result->set_success(false);
        PT_INFO(CONTROL, "Delete generation differs: %ld vs. %ld", params->get_delete_generation(),
                _delete_generation);
        return;
    }
    uint16_t count = 0;
    result->set_success(true);
    result->set_cookie(0); // assume no additional calls are needed

    IList::Node *node = (IList::Node*) params->get_cookie();
    if (node == 0)
        node = _list.get_first();

    size_t size_left = result->get_data_count();
    byte *write_ptr = result->get_data();
    ILIST_ITER_FROM(&_list, i, node) {
        Object *obj = p_container_of(i, Object, list_node);
        size_t object_size = obj->get_clone_size();
        ASSERT_OP(object_size, <=, result->get_data_count());
        if (object_size > size_left) { // additional calls are needed!
            PT_INFO(CONTROL, "Next object to sync from: %p", obj);
            result->set_cookie((uint64_t) i);
            break;
        }
        if (obj->get_generation() >= params->get_from_generation()) { // object modified!
            size_t cloned_size = obj->clone(write_ptr);
            ASSERT_EQUAL(cloned_size, object_size);
            size_left -= object_size;
            write_ptr += object_size;
            count++;
        }
    }
    result->set_count(count);
}

void Tracker::get_deletions(GetDeletionsParams::RootReader *params, GetDeletionsResult::RootBuilder *result)
{
    uint64_t start_generation = params->get_from_generation();
    if (_delete_generation - start_generation > DELETED_OBJECTS_LOG_SIZE ||
        start_generation > _delete_generation) {
        PT_INFO(CONTROL, "Delete generation overflow: %ld vs. %ld", params->get_from_generation(),
                _delete_generation);
        result->set_success(false);
        return;
    }
    result->set_success(true);

    size_t objects_left = result->get_objects_count();
    size_t i = 0;
    while (start_generation < _delete_generation && objects_left > 1) {
        objects_left--;
        *(result->get_objects(i++)) = (uint64_t) _delete_log[(start_generation++) % DELETED_OBJECTS_LOG_SIZE];
    }
    bool has_more = start_generation < _delete_generation;
    result->set_count(i);
    result->set_has_more(has_more);
    PT_INFO(CONTROL, "Returned %zu objects. Has more: %c", i, has_more);
}

Tracker *Tracker::get_current()
{
    return &Silo::get_module()->get_control_agent()->get_metrics_agent()->tracker;
}

}}
