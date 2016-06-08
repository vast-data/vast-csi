/* Copyright (C) Vast Data Ltd. */

#include "record.hpp"

namespace P { namespace Trace {

DEFINE_LOOKUP_IMPLEMENTATION_CPP(TRACE_SEVERITY_LIST,
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
    // the following trace is defined just in case this code is compiled in an executable that doesn't have a single trace
    // in that case, the section isn't created and the __start/stop_traces symbols are not resolved in link time
    static TraceInfo SECTIONIZE(traces) t = {"first trace", __FILE__, "", __LINE__, __func__};
    t.line++; // prevent the compiler from optimizing the trace out

    for (TraceInfo *trace_info = __start_traces; trace_info != __stop_traces; trace_info++) {
        strcpy((char*) trace_info->func, trace_info->func_ptr);
    }
}

}}
