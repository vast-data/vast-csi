/* Copyright (C) Vast Data Ltd. */

/*!
 * \file record.hpp
 */
#pragma once

#include "../utils/macros.hpp"
#include "../utils/types.hpp"

namespace P { namespace Trace {

#define TRACE_SEVERITY_LIST(X)              \
        X(SEVERITY_DEV),                    \
        X(SEVERITY_DEBUG),                  \
        X(SEVERITY_INFO),                   \
        X(SEVERITY_WARN),                   \
        X(SEVERITY_ERROR),                  \
        X(SEVERITY_COUNT)                   \

DEFINE_LOOKUP_PROTOTYPES_CPP(TRACE_SEVERITY_LIST,
                             Severity, // the name of the enum
                             severity_to_string, // the function that converts an enum value to string
                             severity_from_string) // the function that converts a string to an enum value

// The potential maximum record size could be bigger but we pre allocate a trace
// record per silo per component. There's no real reason to allocate more.
const size_t TRACE_RECORD_MAX_SIZE = 4096 * 4;

typedef struct {
    uint64_t time;
    uint32_t job_id;
    uint16_t info_index;
    Severity severity;
    byte params[TRACE_RECORD_MAX_SIZE - (8 + 4 + 2 + 1)];
} TraceRecord;

static_assert(TRACE_RECORD_MAX_SIZE == sizeof(TraceRecord), "TraceRecord size mismatch");

const size_t TRACE_INFO_SIZE = 256; // has to be self-aligned, that's why its defined explicitly

typedef struct {
    byte format[128];
    byte file[64];
    byte func[54];
    uint16_t line;
    const char *func_ptr; // .func starts off empty because __func__ isn't considered a static value. The init_section function sets the value in .func_ptr to .func.
} TraceInfo;

}}

// __start_%s and __stop_%s are automatically set by the linker as the start/end addresses of the section
extern P::Trace::TraceInfo __start_traces[];
extern P::Trace::TraceInfo __stop_traces[];

namespace P { namespace Trace {

static_assert(TRACE_INFO_SIZE == sizeof(TraceInfo), "TraceInfo size mismatch");

static uint16_t get_trace_info_index(TraceInfo *info)
{
    return (uint16_t) (((uintptr_t) info - (uintptr_t) &__start_traces) / sizeof(TraceInfo));
}

static size_t get_trace_section_size()
{
    return (uintptr_t) __stop_traces - (uintptr_t) __start_traces;
}

}}
