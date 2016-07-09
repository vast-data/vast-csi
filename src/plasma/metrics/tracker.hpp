/* Copyright (C) Vast Data Ltd. */

/*!
 * \file tracker.hpp
 * \brief The metrics tracker exposes RPCs for external entities such as management to fetch metric objects data.
 */
#pragma once

#include "plasma/utils/compiler.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/data/ilist.hpp"

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

    //---RPC-functions---
    struct GetGenerationsParams {

    };
    struct GetGenerationsResult {
        uint64_t update_generation;
        uint64_t delete_generation;
    };
    void get_generations(GetGenerationsParams *params, GetGenerationsResult *result);

    struct GetModifiedParams {
        uint64_t delete_generation;
        uint64_t from_generation;
        void *cookie;
    };
    struct GetModifiedResult {
        bool success; // fails if a deletion happened during sync. requires a re-sync.
        uint16_t count;
        void *cookie; // null value indicates end of list.
        byte data[];
    };
    void get_modified(GetModifiedParams *params, GetModifiedResult *result, uint16_t *res_len);

    struct GetDeletionsParams {
        uint64_t from_generation;
    };
    struct GetDeletionsResult {
        bool success; // fails if list has wrapped-around. requires re-sync.
        bool has_more;
        uint16_t count;
        Object *objects[];
    };
    void get_deletions(GetDeletionsParams *params, GetDeletionsResult *result, uint16_t *res_len);

    static Tracker *get_current();

private:
    uint64_t _update_generation; // updated on every metric change or addition of an object.
    uint64_t _delete_generation; // updated on object deletion (addition is safe during iteration).
    Object *_delete_log[DELETED_OBJECTS_LOG_SIZE];
    IList _list;
};

}}
