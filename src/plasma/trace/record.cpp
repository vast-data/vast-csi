/* Copyright (C) Vast Data Ltd. */

#include "record.hpp"
#include "plasma/utils/assert.hpp"

namespace P { namespace Trace {

DEFINE_LOOKUP_IMPLEMENTATION(TRACE_SEVERITY_LIST,
                             Severity,
                             severity_strings,
                             severity_to_string,
                             severity_from_string)

/*!
 * This function initializes the TraceInfo structs by setting the value in .func_ptr to .func.
 * It's required because __func__ isn't considered a static variable and can't be stored in a section at compile time.
 */
static __attribute__ ((constructor)) void init_section()
{
    // the following trace is defined in order to force the linker to define the __start/stop_traces variables.
    static TraceInfo SECTIONIZE("traces") __attribute__((used)) t = {"first trace", __FILE__, "", __LINE__, __func__};

    for (TraceInfo *trace_info = __start_traces; trace_info != __stop_traces; trace_info++) {
        strcpy((char*) trace_info->func, trace_info->func_ptr);
    }
}

}}
