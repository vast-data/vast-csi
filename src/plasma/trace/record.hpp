/* Copyright (C) Vast Data Ltd. */

/*!
 * \file record.hpp
 */
#pragma once

#include <defs.hpp>
#include "../utils/macros.hpp"
#include "../utils/types.hpp"

namespace P { namespace Trace {

#define TRACE_SEVERITY_LIST(X)                             \
        X(DEV),         /* Available only in DEBUG mode */ \
        X(_DEBUG),                                         \
        X(INFO),                                           \
        X(WARN),                                           \
        X(ERROR),                                          \
        X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(TRACE_SEVERITY_LIST, Severity, severity_to_string, severity_from_string)

#define TRACE_CHANNEL_LIST(X) \
    X(DATA),                  \
    X(DETAILED_DATA),         \
    X(CONTROL),               \
    X(PERF),                  \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES(TRACE_CHANNEL_LIST, Channel, channel_to_string, channel_from_string)

// The potential maximum record size could be bigger but we pre allocate a trace
// record per silo per component. There's no real reason to allocate more.
const size_t TRACE_RECORD_MAX_SIZE = 4096 * 4;

struct TraceRecord {
    uint64_t time;
    uint32_t job_id;
    uint16_t info_index;
    Severity severity;
    byte params[TRACE_RECORD_MAX_SIZE - (8 + 4 + 2 + 1)];
};

static_assert(TRACE_RECORD_MAX_SIZE == sizeof(TraceRecord), "TraceRecord size mismatch");

const size_t TRACE_INFO_SIZE = 256; // has to be self-aligned, that's why its defined explicitly
const size_t func_name_size = 40;

struct TraceInfo {
    ComponentId component;
    byte format[128];
    byte file[85];
    uint16_t line;
    union {
        const char *func_ptr; // .func starts off empty because __func__ isn't considered a static value. The init_section function sets the value in .func_ptr to .func.
        byte func[func_name_size];
    };
};

static_assert(TRACE_INFO_SIZE == sizeof(TraceInfo), "TraceInfo size mismatch");

}}

// __start_%s and __stop_%s are automatically set by the linker as the start/end addresses of the section
extern P::Trace::TraceInfo __start_traces[];
extern P::Trace::TraceInfo __stop_traces[];

namespace P { namespace Trace {

static uint16_t get_trace_info_index(TraceInfo *info)
{
    return (uint16_t) (((uintptr_t) info - (uintptr_t) &__start_traces) / sizeof(TraceInfo));
}

static size_t get_trace_section_size()
{
    return (uintptr_t) __stop_traces - (uintptr_t) __start_traces;
}

}}
