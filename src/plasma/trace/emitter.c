/* Copyright (C) Vast Data Ltd. */
#include "emitter.h"
#include "../units.h"
#include "../execution/p_config.h"

DEFINE_LOOKUP_IMPLEMENTATION(SEVERITY_LIST,
                             PTraceSeverity,
                             severity_strings,
                             p_trace_severity_to_string,
                             p_trace_severity_from_string)

__thread PTraceEmitter *p_trace_emitter = NULL;

#define BUFFER_COUNT 4
PTraceEmitter *p_trace_emitter_init(PConfigSetting *setting)
{
    PTraceEmitter *emitter = p_safe_malloc(sizeof(PTraceEmitter));

    // start off with all components disabled (indicated by maximal severity).
    LOOP(COMPONENT_COUNT, i) {
        emitter->min_severity[i] = P_TRACE_SEVERITY_COUNT;
        emitter->buffers[i] = NULL;
    }

    if (setting == NULL)
        return emitter;

    LOOP(p_config_setting_length(setting), i) {
        PConfigSetting *comp_setting = p_config_setting_get_element(setting, (uint32_t) i);
        const char *comp_name = p_config_setting_name(comp_setting);
        ComponentId comp_id = component_id_from_string(comp_name);


        PConfigSetting *buf_size_setting = p_config_setting_lookup_optional(comp_setting, "buffer_size_mb");
        uint32_t buf_size = P_TRACE_EMITTER_DEFAULT_BUF_SIZE_MB;
        if (buf_size_setting != NULL)
            buf_size = (uint32_t) p_config_setting_get_int32(buf_size_setting);
        emitter->buffers[comp_id] = p_dbuffer_init(BUFFER_COUNT, buf_size * UNIT_MiB);

        PConfigSetting *min_severity_setting = p_config_setting_lookup_optional(comp_setting, "min_severity");
        PTraceSeverity min_severity = P_TRACE_DEBUG;
        if (min_severity_setting != NULL)
            min_severity = p_trace_severity_from_string(p_config_setting_get_string(min_severity_setting));
        emitter->min_severity[comp_id] = min_severity;
    }
    return emitter;
}

void p_trace_emitter_destroy(PTraceEmitter *emitter)
{
    LOOP(COMPONENT_COUNT, i) {
        if (emitter->buffers[i] != NULL)
            p_dbuffer_destroy(emitter->buffers[i]);
    }
    p_free(emitter);
}

void p_trace_emitter_set(PTraceEmitter *emitter)
{
    p_trace_emitter = emitter;
}

/*!
 * This function initializes the PTraceInfo structs by setting the value in .func_ptr to .func.
 * It's required because __func__ isn't considered a static variable and can't be stored in a section at compile time.
 */
static __attribute__ ((constructor)) void init_section()
{
    P_ASSERT(sizeof(PTraceInfo) == P_TRACE_INFO_SIZE);
    P_ASSERT(sizeof(PTraceRecord) == P_TRACE_RECORD_MAX_SIZE);

    // the following trace is defined just in case this code is compiled in an executable that doesn't have a single trace
    // in that case, the section isn't created and the __start/stop_traces symbols are not resolved in link time
    static PTraceInfo SECTIONIZE(traces) t = {.format = "first trace",
                                              .func_ptr = __func__,
                                              .file = __FILE__,
                                              .line = __LINE__};
    t.line++; // prevent the compiler from optimizing the trace out

    for (PTraceInfo *trace_info = __start_traces; trace_info != __stop_traces; trace_info++) {
        strcpy((char*) trace_info->func, trace_info->func_ptr);
    }
}
