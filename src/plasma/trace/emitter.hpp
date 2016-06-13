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
#include "defs.hpp"
#include "../execution/config.hpp"
#include "../sync/spin_lock.hpp"
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

    /*!
     * Initialize a trace emitter using a configuration object. An example configuration looks like this:
     \code
     {
         PLASMA: {
             min_severity: "SEVERITY_DEBUG",
             buffer_size_mb: 8
         }
     }
     \endcode
     * The values depicted in the example are the default values.
     *
     * \param setting a ConfigSetting as displayed above.
     * \param shared indicate whether trace calls should be protected with a lock in case the same emitter is used by several threads.
     */
    void init(Conf::ConfigSetting *setting, bool shared);

    void destroy();

    /*!
     * Set this emitter to be used by default by trace calls made from the current pthread.
     */
    void set_local();

    /*!
     * Set this emitter to be used by default if no local emitter was defined.
     */
    void set_global();

    DBuffer *get_dbuffer(ComponentId component); // used only by the dumper

    template<typename... Args>
    static void trace(Severity severity, ComponentId component, TraceInfo *info, Args... args)
    {
        if (!MACRO_IS_SET(DEBUG) && severity == Severity::SEVERITY_DEV)
            return;

        Emitter *emitter = _local_emitter != nullptr ? _local_emitter : _global_emitter;
        if (unlikely(emitter == nullptr || emitter->_min_severity[(byte) component] > severity))
            return;

        // the global emitter is shared between pthreads and has a _lock where the local emitter doesn't need one
        if (unlikely(emitter->_lock))
            emitter->_lock->lock();
        emitter->record_start(info, severity);
        emitter->trace_emit(args...);
        emitter->record_finish(component);
        if (unlikely(emitter->_lock))
            emitter->_lock->unlock();
    }

private:
    DBuffer *_buffers[(byte) ComponentId::COUNT];
    Severity _min_severity[(byte) ComponentId::COUNT];
    TraceRecord _record;
    P_DBUFFER_LENGTH_TYPE _write_index;
    Sync::SpinLock *_lock;

    static thread_local Emitter *_local_emitter;
    static Emitter *_global_emitter;

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
