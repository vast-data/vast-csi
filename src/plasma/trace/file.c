#include <time.h>
#include <stdio.h>
#include <sys/types.h>
#include <stdint.h>
#include <alloca.h>
#include <string.h>
#include <dirent.h>
#include <unistd.h>

#include "../units.h"
#include "../p_assert.h"
#include "../memory/p_alloc.h"
#include "../execution/p_config.h"
#include "emitter.h"
#include "file.h"

#define CHUNK_SIZE UNIT_MiB

struct PTraceFile {
    const char *dir;
    const char *prefix;
    FILE *file;
    uint32_t file_offset;
    uint32_t bytes_left_in_chunk;
    uint32_t max_file_size;
    uint16_t max_files;
};

static void close_file(PTraceFile *trace_file)
{
    P_ASSERT(fclose(trace_file->file) == 0);
}

static void write_file(PTraceFile *trace_file, void *data, size_t length)
{
    P_ASSERT(fwrite(data, length, 1, trace_file->file) == 1);
    trace_file->file_offset += length;
}

static size_t trace_section_size()
{
    return (uintptr_t) __stop_traces - (uintptr_t) __start_traces;
}

#define VERSION 1
static void write_header(PTraceFile *trace_file)
{
    uint16_t version = VERSION;
    write_file(trace_file, &version, sizeof(version));
    size_t section_size = trace_section_size();
    uint16_t num_records = (uint16_t) (section_size / sizeof(PTraceInfo));
    write_file(trace_file, &num_records, sizeof(num_records));
    write_file(trace_file, __start_traces, section_size);
}

#define FILE_SUFFIX_FORMAT ".%y%m%d_%H%M%S_000.trace"
#define FILE_SUFFIX_LENGTH (25) // account for NULL as well
#define FILE_SUFFIX_MILLIS_INDEX (15) // we need to replace 000 with a real value
static void create_file(PTraceFile *trace_file)
{
    P_ASSERT(trace_file->prefix != NULL);

    time_t t;
    struct tm *ltime;

    t = time(NULL);
    ltime = localtime(&t);
    P_ASSERT(ltime != NULL);

    size_t dir_length = strlen(trace_file->dir);
    size_t prefix_length = strlen(trace_file->prefix);
    char path[dir_length + 1 + prefix_length + FILE_SUFFIX_LENGTH + 1];
    snprintf(path, dir_length + 1 + prefix_length + 1, "%s/%s", trace_file->dir, trace_file->prefix);
    char *suffix = path + dir_length + 1 + prefix_length;

    P_ASSERT(strftime(suffix, FILE_SUFFIX_LENGTH, FILE_SUFFIX_FORMAT, ltime) == FILE_SUFFIX_LENGTH - 1);
    uint32_t millis = NANO_TO_MILLI(p_get_time_nano()) % 1000;
    P_ASSERT(snprintf(suffix + FILE_SUFFIX_MILLIS_INDEX, 4, "%03d", millis) == 3);
    suffix[FILE_SUFFIX_MILLIS_INDEX + 3] = '.';

    P_ASSERT(access(path, F_OK) == -1);
    trace_file->file = fopen(path, "w");
    P_ASSERT(trace_file->file != NULL);
    trace_file->file_offset = 0;
    trace_file->bytes_left_in_chunk = CHUNK_SIZE;
    write_header(trace_file);
}

PTraceFile *p_trace_file_init(const char *prefix, const char *dir, uint32_t max_file_size, uint16_t max_files)
{
    PTraceFile *trace_file = p_safe_malloc(sizeof(PTraceFile));
    trace_file->prefix = prefix;
    trace_file->dir = dir;
    trace_file->max_file_size = max_file_size;
    trace_file->max_files = max_files;
    trace_file->bytes_left_in_chunk = CHUNK_SIZE;
    trace_file->file = NULL;
    return trace_file;
}

#define DEFAULT_FILE_SIZE_MB (512)
#define DEFAULT_FILE_COUNT (20)
PTraceFile *p_trace_file_init_from_setting(const char *prefix, const char *dir, PConfigSetting *setting)
{
    PConfigSetting *file_size_setting = p_config_setting_lookup_optional(setting, "file_size_mb");
    uint32_t file_size = DEFAULT_FILE_SIZE_MB;
    if (file_size_setting != NULL)
        file_size = (uint32_t) p_config_setting_get_int32(file_size_setting);

    PConfigSetting *file_count_setting = p_config_setting_lookup_optional(setting, "file_count");
    uint16_t file_count = DEFAULT_FILE_COUNT;
    if (file_count_setting != NULL)
        file_count = (uint16_t) p_config_setting_get_int32(file_count_setting);
    return p_trace_file_init(prefix, dir, file_size * UNIT_MiB, file_count);
}

void p_trace_file_set_prefix(PTraceFile *trace_file, const char *prefix)
{
    trace_file->prefix = prefix;
}

void p_trace_file_destroy(PTraceFile *trace_file)
{
    if (trace_file->file != NULL)
        close_file(trace_file);
    p_free(trace_file);
}

#define MAX_PATH (512)
static void delete_files_if_needed(PTraceFile *trace_file)
{
    char path[MAX_PATH];
    struct dirent **namelist;
    int32_t n = scandir(trace_file->dir, &namelist, NULL, alphasort);
    P_ASSERT(n >= 0);
    uint16_t max_files = trace_file->max_files;
    while (n--) {
        if (strncmp(namelist[n]->d_name, trace_file->prefix, strlen(trace_file->prefix)) == 0) {
            if (max_files == 0) {
                snprintf(path, MAX_PATH, "%s/%s", trace_file->dir, namelist[n]->d_name);
                int remove_result = remove(path);
                P_ASSERT(remove_result == 0);
            } else {
                max_files--;
            }
        }
        free(namelist[n]);
    }
    free(namelist);
}

static void rotate_file_if_needed(PTraceFile *trace_file, uint8_t length)
{
    if (trace_file->file_offset + length > trace_file->max_file_size) {
        close_file(trace_file);
        create_file(trace_file);
        delete_files_if_needed(trace_file);
    }
}

static void rotate_chunk_if_needed(PTraceFile *trace_file, uint8_t length)
{
    if (length > trace_file->bytes_left_in_chunk) {
        P_ASSERT(fseek(trace_file->file, trace_file->bytes_left_in_chunk, SEEK_CUR) == 0);
        P_ASSERT(ftell(trace_file->file) % CHUNK_SIZE == trace_section_size() + 2 + 2);
        trace_file->file_offset += trace_file->bytes_left_in_chunk;
        trace_file->bytes_left_in_chunk = CHUNK_SIZE;
    }
}

void p_trace_file_emit(PTraceFile *trace_file, PTraceRecord *record, uint8_t length)
{
    if (trace_file->file == NULL)
        create_file(trace_file);
    rotate_chunk_if_needed(trace_file, length + 1);
    rotate_file_if_needed(trace_file, length + 1);
    write_file(trace_file, &length, sizeof(uint8_t));
    write_file(trace_file, record, length);
    trace_file->bytes_left_in_chunk -= (length + 1);
}
