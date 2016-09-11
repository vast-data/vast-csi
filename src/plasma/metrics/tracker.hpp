/* Copyright (C) Vast Data Ltd. */

/*!
 * \file tracker.hpp
 * \brief The metrics tracker exposes RPCs for external entities such as management to fetch metric objects data.
 */
#pragma once

#include "plasma/utils/compiler.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/data/ilist.hpp"
#include "tracker.vproto.hpp"

namespace P { namespace Metrics {

static const uint32_t DELETED_OBJECTS_LOG_SIZE = 1024;

class Object;

class Tracker {

public:
    void init();
    void destroy();
    void on_object_init(Object *object);
    void on_object_destroy(Object *object);
    uint64_t next_generation()
    {
        return _update_generation++;
    }
    IList *get_list();

    static Tracker *get_current();

    //---RPC-functions---
    void get_generations(GetGenerationsParams::RootReader *params, GetGenerationsResult::RootBuilder *result);
    void get_modified(GetModifiedParams::RootReader *params, GetModifiedResult::RootBuilder *result);
    void get_deletions(GetDeletionsParams::RootReader *params, GetDeletionsResult::RootBuilder *result);

private:
    uint64_t _update_generation; // updated on every metric change or addition of an object.
    uint64_t _delete_generation; // updated on object deletion (addition is safe during iteration).
    Object *_delete_log[DELETED_OBJECTS_LOG_SIZE];
    IList _list;
};

}}
