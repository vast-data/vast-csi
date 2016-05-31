#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>
#include <unistd.h>

#include "../execution/p_config.h"
#include "../memory/p_alloc.h"
#include "../utils.h"
#include "dumper.h"

#define MAX_PREFIX_SIZE 128
struct PTraceDumper {
    PDbufferReader *readers[COMPONENT_COUNT];
    PTraceFile *files[COMPONENT_COUNT];
    char file_prefixes[COMPONENT_COUNT][MAX_PREFIX_SIZE];
    uint64_t times[COMPONENT_COUNT];
    PTraceEmitter *emitter;
    pthread_t pthread;
    uint32_t bytes_written;
    volatile bool stop;
    volatile bool running;
};

#define P_TRACE_DUMPER_DEFAULT_PERSISTENT (true)
PTraceDumper *p_trace_dumper_init(PConfigSetting *setting, PTraceEmitter *emitter, const char *dir)
{
    p_ensure_directory_exists(dir);
    PTraceDumper *dumper = p_safe_malloc(sizeof(PTraceDumper));
    dumper->stop = false;
    dumper->running = false;
    dumper->bytes_written = 0;
    dumper->emitter = emitter;

    LOOP(COMPONENT_COUNT, i) {
        dumper->readers[i] = NULL;
        dumper->times[i] = 0;
    }

    LOOP(p_config_setting_length(setting), i) {
        PConfigSetting *comp_setting = p_config_setting_get_element(setting, (uint32_t) i);
        const char *comp_name = p_config_setting_name(comp_setting);
        ComponentId comp_id = component_id_from_string(comp_name);

        dumper->readers[comp_id] = p_safe_malloc(sizeof(PDbufferReader));
        p_dbuffer_reader_init(dumper->readers[comp_id], emitter->buffers[comp_id]);

        PConfigSetting *persistent_setting = p_config_setting_lookup_optional(comp_setting, "persistent");
        bool persistent = P_TRACE_DUMPER_DEFAULT_PERSISTENT;
        if (persistent_setting != NULL)
            persistent = p_config_setting_get_bool(persistent_setting);

        if (!persistent)
            continue;

        dumper->files[comp_id] = p_trace_file_init_from_setting(NULL, dir, comp_setting);
    }
    return dumper;
}

void p_trace_dumper_destroy(PTraceDumper *dumper)
{
    P_ASSERT(!dumper->running);
    LOOP(COMPONENT_COUNT, i) {
        if (dumper->readers[i] != NULL) {
            p_free(dumper->readers[i]);
            if (dumper->files[i] != NULL) {
                p_trace_file_destroy(dumper->files[i]);
            }
        }
    }
    p_free(dumper);
}

static bool dumper_iteration(PTraceDumper *dumper, bool force)
{
    static PTraceInfo SECTIONIZE(traces) overflow_info = {.format = "Trace overflow. %hd buffers lost.",
                                                          .func_ptr = __func__,
                                                          .file = __FILE__,
                                                          .line = __LINE__};
    uint16_t overflow_index = p_trace_info_index(&overflow_info);

    PTraceRecord record;
    P_DBUFFER_LENGTH_TYPE length;
    bool found = false;
    LOOP(COMPONENT_COUNT, i) {
        if (dumper->readers[i] != NULL) {
            PDbufferReadResult read_result = p_dbuffer_read(dumper->readers[i], &record, &length, force);
            switch (read_result) {
            case PDBUFFER_READ_NOTHING:
                break;
            case PDBUFFER_READ_SUCCESS:
                dumper->times[i] = record.time;
                p_trace_file_emit(dumper->files[i], &record, length);
                found = true;
                break;
            case PDBUFFER_READ_OVERFLOW:
                found = true;
                // set the time of the last record emitted for this component.
                // the reader expects timestamps to be monotonically increasing (does a merge sort).
                record.time = dumper->times[i];
                record.job_id = 0; // no fiber
                record.severity = P_TRACE_ERROR;
                record.info_index = overflow_index;
                memcpy(record.params, &length, sizeof(length));
                p_trace_file_emit(dumper->files[i], &record, offsetof(PTraceRecord, params) + sizeof(length));
                break;
            }
        }
    }
    return found;
}

#define IDLE_SLEEP_MICROS 10
static void *dumper_main(void *dumper_arg)
{
    PTraceDumper *dumper = dumper_arg;
    dumper->running = true;
    while (!dumper->stop) {
        if (!dumper_iteration(dumper, false))
            usleep(IDLE_SLEEP_MICROS);
    }
    while (dumper_iteration(dumper, true)) {

    }
    dumper->running = false;
    return NULL;
}

#include <sys/syscall.h>

void p_trace_dumper_start(PTraceDumper *dumper)
{
    P_ASSERT(!dumper->running);
    dumper->stop = false;

    LOOP(COMPONENT_COUNT, i) {
        dumper->running = true;
        const char *comp = component_id_to_string((ComponentId) i) + 10; // skip the COMPONENT_
        snprintf(dumper->file_prefixes[i], MAX_PREFIX_SIZE, "%s.%ld", comp, syscall(SYS_gettid));
        p_trace_file_set_prefix(dumper->files[i], dumper->file_prefixes[i]);
    }

    P_ASSERT(pthread_create(&dumper->pthread, NULL, dumper_main, dumper) == 0);
}

void p_trace_dumper_stop(PTraceDumper *dumper)
{
    dumper->stop = true;
}

#define WAIT_SLEEP_MICROS 100
void p_trace_dumper_wait(PTraceDumper *dumper)
{
    while (dumper->running)
        usleep(WAIT_SLEEP_MICROS);
}
