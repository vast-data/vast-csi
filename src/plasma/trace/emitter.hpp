/* Copyright (C) Vast Data Ltd. */

/*!
 * \file emitter.hpp
 * \brief The trace user interface. The functions the user needs to know are PT_DEV, PT_DEBUG, PT_INFO, PT_WARN, PT_ERROR.
 * PT_DEV is compiled out unless we're in debug mode. The aforementioned functions expect to run within a component's code;
 * They rely on the CURRENT_COMPONENT macro to deduce what component is the trace originating from.The trace file encapsulates the logic of splitting a stream of traces into files.
 */
#pragma once

#include <cstring>
#include "record.hpp"
#include "dbuffer.hpp"
#include "vdefs.hpp"
#include "../execution/config.hpp"
#include "../utils/macros.hpp"
#include "../fiber/fiber.hpp"
#include "../utils/time.hpp"

#define P_TRACE(severity, component, fmt, ...) do {                                 \
        static P::Trace::TraceInfo SECTIONIZE(traces) info = {fmt, __FILE__, "<temp>", __LINE__, __func__}; \
        P::Trace::validate_format(fmt, ##__VA_ARGS__);                              \
        P::Trace::Emitter::trace(severity, component, &info, ##__VA_ARGS__);        \
} while(0)

#define PT_DEV(...) P_TRACE(P::Trace::Severity::SEVERITY_DEV, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_DEBUG(...) P_TRACE(P::Trace::Severity::SEVERITY_DEBUG, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_INFO(...) P_TRACE(P::Trace::Severity::SEVERITY_INFO, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_WARN(...) P_TRACE(P::Trace::Severity::SEVERITY_WARN, CURRENT_COMPONENT, __VA_ARGS__)
#define PT_ERROR(...) P_TRACE(P::Trace::Severity::SEVERITY_ERROR, CURRENT_COMPONENT, __VA_ARGS__)

#define P_TRACE_MAX_STR_LEN 4096
#define P_TRACE_STR_LEN_TYPE uint16_t

namespace P { namespace Trace {

class Emitter {
public:
    void init(Conf::ConfigSetting *setting);
    void destroy();
    void set();
    DBuffer *get_dbuffer(ComponentId component); // used only by the dumper

    static thread_local Emitter *_emitter;

    template<typename... Args>
    static void trace(Severity severity, ComponentId component, TraceInfo *info, Args... args)
    {
        if (!MACRO_IS_SET(DEBUG) && severity == Severity::SEVERITY_DEV)
            return;
        if (unlikely(_emitter == nullptr || _emitter->_min_severity[(byte) component] > severity))
            return;
        _emitter->record_start(info, severity);
        _emitter->trace_emit(args...);
        _emitter->record_finish(component);
    }

private:
    DBuffer *_buffers[(byte) ComponentId::COUNT];
    Severity _min_severity[(byte) ComponentId::COUNT];
    TraceRecord _record;
    P_DBUFFER_LENGTH_TYPE _write_index;

    void record_start(TraceInfo *info, Severity severity)
    {
        Fiber *fiber = Fiber::get_current();
        if (fiber != nullptr)
            _record.job_id = fiber->get_job_id();
        else
            _record.job_id = 0; // trace records emitted before running within a scheduler
        _record.time = get_time_nano();
        _record.info_index = get_trace_info_index(info);
        _record.severity = severity;
        _write_index = 0;
    }

    void record_finish(ComponentId comp)
    {
        _buffers[(byte) comp]->write(&_record, offsetof(TraceRecord, params) + _write_index);
    }

    void emit_param(const void *data, P_DBUFFER_LENGTH_TYPE length)
    {
        DEBUG_ASSERT_OP(TRACE_RECORD_MAX_SIZE - (_write_index + offsetof(TraceRecord, params)), >, length);
        memcpy(&_record.params[_write_index], data, length);
        _write_index += length;
    }

    void trace_emit_param(const char *value)
    {
        size_t length = strnlen(value, P_TRACE_MAX_STR_LEN);
        P_TRACE_STR_LEN_TYPE short_length = (P_TRACE_STR_LEN_TYPE) length;
        if (length == P_TRACE_MAX_STR_LEN) { // string too big
            short_length = P_TRACE_MAX_STR_LEN;
            emit_param(&short_length, sizeof(short_length));
            emit_param(value, short_length - 1);
            char null = '\0';
            emit_param(&null, 1);
        } else {
            emit_param(&short_length, sizeof(short_length));
            emit_param(value, short_length);
        }
    }

    template<typename T>
    void trace_emit_param(T arg)
    {
        emit_param(&arg, sizeof(T));
    }

    void trace_emit()
    {

    }

    template<typename T, typename... Args>
    void trace_emit(T value, Args... args)
    {
        trace_emit_param(value);
        trace_emit(args...);
    }

};

static __attribute__ ((format (printf, 1, 2))) void validate_format(const char *format, ...)
{

}

}}
