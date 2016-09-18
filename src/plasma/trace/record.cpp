/* Copyright (C) Vast Data Ltd. */

#include <plasma/internal.hpp>
#include "record.hpp"
#include "plasma/utils/assert.hpp"

namespace P { namespace Trace {

DEFINE_LOOKUP_IMPLEMENTATION(TRACE_SEVERITY_LIST, Severity, severity_strings, severity_to_string, severity_from_string)
DEFINE_LOOKUP_IMPLEMENTATION(TRACE_CHANNEL_LIST, Channel, channel_strings, channel_to_string, channel_from_string)

/*!
 * This function initializes the TraceInfo structs by setting the value in .func_ptr to .func.
 * It's required because __func__ isn't considered a static variable and can't be stored in a section at compile time.
 */
static __attribute__ ((constructor)) void init_section()
{
    // the following trace is defined in order to force the linker to define the __start/stop_traces variables.
    static TraceInfo SECTIONIZE("traces") __attribute__((used)) t = {
        CURRENT_COMPONENT, "first trace", __FILE__, __LINE__, {__func__}
    };

    for (TraceInfo *trace_info = __start_traces; trace_info != __stop_traces; trace_info++) {
        size_t func_len = strlen(trace_info->func_ptr);
        if (func_len > sizeof trace_info->func - 1)
            func_len = sizeof trace_info->func - 1;
        strncpy((char*)trace_info->func, trace_info->func_ptr, func_len);
        trace_info->func[func_len] = '\0';
    }
}

}}
