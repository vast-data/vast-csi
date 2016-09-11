/* Copyright (C) Vast Data Ltd. */

/*!
 * \file emitter.hpp
 * \brief The trace user interface. The functions the user needs to know are PT_DEV, PT_DEBUG, PT_INFO, PT_WARN, PT_ERROR.
 * PT_DEV is compiled out unless we're in debug mode. The aforementioned functions expect to run within a component's code;
 * They rely on the CURRENT_COMPONENT macro to deduce what component is the trace originating from.The trace file encapsulates the logic of splitting a stream of traces into files.
 */
#pragma once

#include <cstring>
#include <cstddef>
#include "record.hpp"
#include "dbuffer.hpp"
#include "defs.hpp"
#include "../execution/config.hpp"
#include "../sync/spin_lock.hpp"
#include "../utils/compiler.hpp"
#include "../utils/macros.hpp"
#include "../utils/time.hpp"

#ifdef __clang__
  #define TRACE_SECTION SECTIONIZE("traces")
#else
  #define _TRACE_SECTION(file, line) SECTIONIZE("traces." file line)
  #define TRACE_SECTION _TRACE_SECTION(__FILE__, MACRO_STRINGIFY(__LINE__))
#endif

#define P_TRACE(channel, severity, component, fmt, ...) do {                                 \
        static P::Trace::TraceInfo TRACE_SECTION info = {component, fmt, __FILE__, __LINE__, __func__}; \
        P::Trace::validate_format(fmt, ##__VA_ARGS__);                              \
        P::Trace::Emitter::trace(channel, severity, &info, ##__VA_ARGS__);        \
} while(0)

#define PT_HELPER(channel, severity, ...) \
    P_TRACE(P::Trace::Channel:: channel, P::Trace::Severity:: severity, CURRENT_COMPONENT, __VA_ARGS__)

// Convenience macros for specific severities:
// Example: PT_INFO(DATA, "Here's the data: %d", i);
#define PT_DEV(channel, ...) PT_HELPER(channel, DEV, __VA_ARGS__)
#define PT_DEBUG(channel, ...) PT_HELPER(channel, _DEBUG, __VA_ARGS__)
#define PT_INFO(channel, ...) PT_HELPER(channel, INFO, __VA_ARGS__)
#define PT_WARN(channel, ...) PT_HELPER(channel, WARN, __VA_ARGS__)
#define PT_ERROR(channel, ...) PT_HELPER(channel, ERROR, __VA_ARGS__)

#define PT_RETURN(COND, RETVAL, FMT, ...)    \
    if (COND) {                         \
        PT_ERROR(DATA, FMT " - retval=%lu", ##__VA_ARGS__, (uint64_t)RETVAL);    \
        return RETVAL;                  \
    }

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
             min_severity: "DEBUG",
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
     * Flush buffers so the trace dumper could write data to disk.
     */
    void flush();

    /*!
     * Set this emitter to be used by default by trace calls made from the current pthread.
     */
    void set_local();

    /*!
     * Set this emitter to be used by default if no local emitter was defined.
     */
    void set_global();
    static Emitter *get_global() { return _global_emitter; }

    DBuffer *get_dbuffer(Channel channel); // used only by the dumper

    template<typename... Args>
    static void trace(Channel channel, Severity severity, TraceInfo *info, Args... args)
    {
        if (!MACRO_IS_SET(DEBUG) && severity == Severity::DEV)
            return;

        Emitter *emitter = _local_emitter != nullptr ? _local_emitter : _global_emitter;
        if (unlikely(emitter == nullptr || emitter->_min_severity[(byte) info->component] > severity))
            return;

        // the global emitter is shared between pthreads and has a _lock where the local emitter doesn't need one
        if (unlikely(emitter->_lock))
            emitter->_lock->lock();
        emitter->record_start(info, severity);
        emitter->trace_emit(args...);
        emitter->record_finish(channel);
        if (unlikely(emitter->_lock))
            emitter->_lock->unlock();
    }

private:
    DBuffer *_buffers[(byte) Channel::COUNT];
    Severity _min_severity[(byte) ComponentId::COUNT];
    TraceRecord _record;
    P_DBUFFER_LENGTH_TYPE _write_index;
    Sync::SpinLock *_lock;

    static thread_local Emitter *_local_emitter;
    static Emitter *_global_emitter;

    uint64_t get_fiber_id();

    void record_start(TraceInfo *info, Severity severity)
    {
        _record.job_id = get_fiber_id();
        _record.time = get_time_nano();
        _record.info_index = get_trace_info_index(info);
        _record.severity = severity;
        _write_index = 0;
    }

    void record_finish(Channel channel)
    {
        _buffers[(byte) channel]->write(&_record, offsetof(TraceRecord, params) + _write_index);
    }

    void emit_param(const void *data, P_DBUFFER_LENGTH_TYPE length)
    {
        // we can't use asserts from this header as the asserts rely on it..
        //DEBUG_ASSERT_OP(TRACE_RECORD_MAX_SIZE - (_write_index + offsetof(TraceRecord, params)), >, length);
        memcpy(&_record.params[_write_index], data, length);
        _write_index += length;
    }

    void trace_emit_param(char *value)
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

    void trace_emit_param(const char *value)
    {
        trace_emit_param((char*) value);
    }

    template<typename T>
    void trace_emit_param(T arg)
    {
        emit_param(&arg, sizeof(T));
        // temporary workaround for ORION-35
        if (sizeof(T) < 4) {
            int zero = 0;
            emit_param(&zero, (uint16_t) (4 - sizeof(T)));
        }
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
