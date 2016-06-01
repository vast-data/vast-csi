/* Copyright (C) Vast Data Ltd. */

/*!
 * \file emitter.h
 * \brief The trace user interface. The functions the user needs to know are PT_DEV, PT_DEBUG, PT_INFO, PT_WARN, PT_ERROR.
 * PT_DEV is compiled out unless we're in debug mode. The aforementioned functions expect to run within a component's code;
 * They rely on the CURRENT_COMPONENT macro to deduce what component is the trace originating from.
 */
#pragma once

#include <string.h>
#include <stddef.h>

#include "defs.h"
#include "../p_assert.h"
#include "../macro.h"
#include "../time.h"
#include "../fiber/p_fiber.h"

#include "p_dbuffer.h"

#define SEVERITY_LIST(X)                       \
    X(P_TRACE_DEV),                            \
    X(P_TRACE_DEBUG),                          \
    X(P_TRACE_INFO),                           \
    X(P_TRACE_WARN),                           \
    X(P_TRACE_ERROR),                          \
    X(P_TRACE_SEVERITY_COUNT)                  \

DEFINE_LOOKUP_PROTOTYPES(SEVERITY_LIST,
                         PTraceSeverity, // the name of the enum
                         p_trace_severity_to_string, // the function that converts an enum value to string
                         p_trace_severity_from_string) // the function that converts a string to an enum value

#define P_TRACE_INFO_SIZE 256 // this number has to be self-aligned, that's why its not defined as a simple sizeof
typedef struct {
    uint8_t format[128];
    uint8_t file[64];
    uint8_t func[54];
    uint16_t line;
    const char *func_ptr; // .func starts off empty because __func__ isn't considered a static value. The init_section function sets the value in .func_ptr to .func.
} PTraceInfo;

// The potential maximum record size could be bigger but we pre allocate a trace
// record per silo per component. There's no real reason to allocate more.
#define P_TRACE_RECORD_MAX_SIZE (4096 * 4)
typedef struct {
    uint64_t time;
    uint32_t job_id;
    uint16_t info_index;
    uint8_t severity;
    uint8_t params[P_TRACE_RECORD_MAX_SIZE - (8 + 4 + 2 + 1)];
} PTraceRecord;

typedef struct {
    PDbuffer *buffers[COMPONENT_COUNT];
    PTraceSeverity min_severity[COMPONENT_COUNT];
    PTraceRecord record;
    P_DBUFFER_LENGTH_TYPE write_index;
} PTraceEmitter;

extern __thread PTraceEmitter *p_trace_emitter;

PTraceEmitter *p_trace_emitter_init(PConfigSetting *setting);
void p_trace_emitter_destroy(PTraceEmitter *emitter);
void p_trace_emitter_set(PTraceEmitter *emitter);

#define P_TRACE_EMITTER_DEFAULT_BUF_SIZE_MB (8)
#define P_TRACE_ARG(arg) _Generic((arg),                                  \
                                  const char*: p_trace_arg_string,        \
                                  char*: p_trace_arg_string,              \
                                  const void*: p_trace_arg_ptr,           \
                                  void*: p_trace_arg_ptr,                 \
                                  char: p_trace_arg_char,                 \
                                  short: p_trace_arg_short,               \
                                  int: p_trace_arg_int,                   \
                                  long: p_trace_arg_long,                 \
                                  bool: p_trace_arg_bool,                 \
                                  float: p_trace_arg_float,               \
                                  double: p_trace_arg_double              \
        )(arg);

// __start_%s and __stop_%s are automatically set by the linker as the start/end addresses of the section
extern PTraceInfo __start_traces[];
extern PTraceInfo __stop_traces[];

static inline uint16_t p_trace_info_index(PTraceInfo *info)
{
    return (uint16_t) (((uintptr_t) info - (uintptr_t) &__start_traces) / sizeof(PTraceInfo));
}

#define SECTIONIZE(name) __attribute__ ((section (#name)))
#define P_TRACE(severity, component, fmt, ...) do {                                                    \
    if (!MACRO_IS_SET(DEBUG) && severity == P_TRACE_DEV)                                               \
        break;                                                                                         \
    if (p_trace_emitter == NULL || p_trace_emitter->min_severity[component] > severity)                \
        break;                                                                                         \
    p_validate_format(fmt, ##__VA_ARGS__);                                                             \
    static PTraceInfo SECTIONIZE(traces) info = {.format = fmt,                                        \
                                                 .func_ptr = __func__,                                 \
                                                 .file = __FILE__,                                     \
                                                 .line = __LINE__};                                    \
    uint16_t info_index = p_trace_info_index(&info);                                                   \
    p_trace_record_start(info_index, severity);                                                        \
    CALL_MACRO_X_FOR_EACH(P_TRACE_ARG, ##__VA_ARGS__)                                                  \
    p_trace_record_finish(component);                                                                  \
} while(0)

#define PT_DEV(...) P_TRACE(P_TRACE_DEV, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_DEBUG(...) P_TRACE(P_TRACE_DEBUG, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_INFO(...) P_TRACE(P_TRACE_INFO, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_WARN(...) P_TRACE(P_TRACE_WARN, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_ERROR(...) P_TRACE(P_TRACE_ERROR, CURRENT_COMPONENT, __VA_ARGS__)

static inline __attribute__ ((format (printf, 1, 2))) void p_validate_format(const char *format, ...)
{
    (void) format;
}

static inline void p_emit_param(const void *data, uint16_t length)
{
    P_DEBUG_ASSERT(P_TRACE_RECORD_MAX_SIZE - (p_trace_emitter->write_index + offsetof(PTraceRecord, params)) > length);
    memcpy(&p_trace_emitter->record.params[p_trace_emitter->write_index], data, length);
    p_trace_emitter->write_index += length;
}

static inline void p_trace_record_start(uint16_t info_index, PTraceSeverity severity)
{
    PFiber *fiber = p_get_current_fiber();
    if (fiber != NULL)
        p_trace_emitter->record.job_id = p_fiber_get_job_id(fiber);
    else
        p_trace_emitter->record.job_id = 0; // trace records emitted before running within a scheduler
    p_trace_emitter->record.time = p_get_time_nano();
    p_trace_emitter->record.info_index = info_index;
    p_trace_emitter->record.severity = severity;
    p_trace_emitter->write_index = 0;
}

static inline void p_trace_record_finish(ComponentId comp)
{
    p_dbuffer_write(p_trace_emitter->buffers[comp], &p_trace_emitter->record, offsetof(PTraceRecord, params) + p_trace_emitter->write_index);
}

#define P_TRACE_MAX_STR_LEN 4096
#define P_TRACE_STR_LEN_TYPE uint16_t
static inline void p_trace_arg_string(const char *value)
{
    size_t length = strlen(value);
    P_ASSERT(length < P_TRACE_MAX_STR_LEN);
    P_TRACE_STR_LEN_TYPE short_length = (P_TRACE_STR_LEN_TYPE) length;
    p_emit_param(&short_length, sizeof(short_length));
    p_emit_param(value, short_length);
}

static inline void p_trace_arg_ptr(const void *value)
{
    p_emit_param(&value, sizeof(void*));
}

static inline void p_trace_arg_int(int value)
{
    p_emit_param(&value, sizeof(int));
}

static inline void p_trace_arg_long(long value)
{
    p_emit_param(&value, sizeof(long));
}

static inline void p_trace_arg_short(short value)
{
    p_emit_param(&value, sizeof(short));
}

static inline void p_trace_arg_char(char value)
{
    p_emit_param(&value, sizeof(char));
}

static inline void p_trace_arg_bool(bool value)
{
    p_emit_param(&value, sizeof(bool));
}

static inline void p_trace_arg_float(float value)
{
    p_emit_param(&value, sizeof(float));
}

static inline void p_trace_arg_double(double value)
{
    p_emit_param(&value, sizeof(double));
}
