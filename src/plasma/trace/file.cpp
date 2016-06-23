/* Copyright (C) Vast Data Ltd. */
#include "file.hpp"

#include <unistd.h>
#include <limits.h>
#include <dirent.h>
#include "record.hpp"
#include "plasma/utils/units.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/utils/time.hpp"

#define VERSION (1)
#define CHUNK_SIZE UNIT_MiB
#define DEFAULT_FILE_SIZE_MB (512)
#define DEFAULT_FILE_COUNT (20)
#define FILE_SUFFIX_FORMAT ".%y%m%d_%H%M%S_000.trace"
#define FILE_SUFFIX_LENGTH (25) // account for NULL as well
#define FILE_SUFFIX_MILLIS_INDEX (15) // we need to replace 000 with a real value

using namespace P::Conf;

namespace P { namespace Trace {

void TraceFile::init(const char *prefix, const char *dir, uint32_t max_file_size, uint16_t max_files)
{
    _prefix = prefix;
    _dir = dir;
    _max_file_size = max_file_size;
    _max_files = max_files;
    _bytes_left_in_chunk = CHUNK_SIZE;
    _file = nullptr;
}

void TraceFile::init_from_setting(const char *prefix, const char *dir, Conf::ConfigSetting *setting)
{
    ConfigSetting *file_size_setting = conf_setting_lookup_optional(setting, "file_size_mb");
    uint32_t file_size = DEFAULT_FILE_SIZE_MB;
    if (file_size_setting != nullptr)
        file_size = (uint32_t) conf_setting_get_int32(file_size_setting);

    ConfigSetting *file_count_setting = conf_setting_lookup_optional(setting, "file_count");
    uint16_t file_count = DEFAULT_FILE_COUNT;
    if (file_count_setting != nullptr)
        file_count = (uint16_t) conf_setting_get_int32(file_count_setting);
    init(prefix, dir, file_size * UNIT_MiB, file_count);
}

void TraceFile::set_prefix(const char *prefix)
{
    _prefix = prefix;
}

void TraceFile::destroy()
{
    if (_file != nullptr)
        close_file();
}

void TraceFile::emit(TraceRecord *record, P_DBUFFER_LENGTH_TYPE length)
{
    if (_file == nullptr)
        create_file();
    rotate_chunk_if_needed(length + P_DBUFFER_LENGTH_BYTES);
    rotate_file_if_needed(length + P_DBUFFER_LENGTH_BYTES);
    write_file(&length, P_DBUFFER_LENGTH_BYTES);
    write_file(record, length);
    _bytes_left_in_chunk -= (length + P_DBUFFER_LENGTH_BYTES);
}

void TraceFile::create_file()
{
    ASSERT_OP(_prefix, !=, nullptr);

    time_t t;
    struct tm *ltime;

    t = time(nullptr);
    ltime = localtime(&t);
    ASSERT_NOT_NULL(ltime);

    size_t dir_length = strlen(_dir);
    size_t prefix_length = strlen(_prefix);
    char path[dir_length + 1 + prefix_length + FILE_SUFFIX_LENGTH + 1];
    snprintf(path, dir_length + 1 + prefix_length + 1, "%s/%s", _dir, _prefix);
    char *suffix = path + dir_length + 1 + prefix_length;

    ASSERT_EQUAL(strftime(suffix, FILE_SUFFIX_LENGTH, FILE_SUFFIX_FORMAT, ltime), FILE_SUFFIX_LENGTH - 1);
    uint32_t millis = NANO_TO_MILLI(get_time_nano()) % 1000;
    ASSERT_EQUAL(snprintf(suffix + FILE_SUFFIX_MILLIS_INDEX, 4, "%03d", millis), 3);
    suffix[FILE_SUFFIX_MILLIS_INDEX + 3] = '.';

    ASSERT_EQUAL(access(path, F_OK), -1);
    _file = fopen(path, "w");
    ASSERT_NOT_NULL(_file);
    _file_offset = 0;
    _bytes_left_in_chunk = CHUNK_SIZE;
    write_header();
}

void TraceFile::close_file()
{
    ASSERT_EQUAL(fclose(_file), 0);
}

void TraceFile::write_header()
{
    uint16_t version = VERSION;
    write_file(&version, sizeof(version));
    size_t section_size = get_trace_section_size();
    uint16_t num_records = (uint16_t) (section_size / sizeof(TraceInfo));
    write_file(&num_records, sizeof(num_records));
    write_file(__start_traces, section_size);
}

void TraceFile::write_file(void *data, size_t length)
{
    ASSERT_EQUAL(fwrite_unlocked(data, length, 1, _file), 1);
    _file_offset += length;
}

void TraceFile::rotate_file_if_needed(P_DBUFFER_LENGTH_TYPE length)
{
    if (_file_offset + length > _max_file_size) {
        close_file();
        create_file();
        delete_files_if_needed();
    }
}

void TraceFile::rotate_chunk_if_needed(P_DBUFFER_LENGTH_TYPE length)
{
    if (length > _bytes_left_in_chunk) {
        ASSERT_EQUAL(fseek(_file, _bytes_left_in_chunk, SEEK_CUR), 0);
        ASSERT_EQUAL(ftell(_file) % CHUNK_SIZE, get_trace_section_size() + 2 + 2);
        _file_offset += _bytes_left_in_chunk;
        _bytes_left_in_chunk = CHUNK_SIZE;
    }
}

void TraceFile::delete_files_if_needed()
{
    char path[PATH_MAX];
    struct dirent **namelist;
    int32_t n = scandir(_dir, &namelist, nullptr, alphasort);
    ASSERT_OP(n, >=, 0);
    uint16_t max_files = _max_files;
    while (n--) {
        if (strncmp(namelist[n]->d_name, _prefix, strlen(_prefix)) == 0) {
            if (max_files == 0) {
                snprintf(path, PATH_MAX, "%s/%s", _dir, namelist[n]->d_name);
                int remove_result = remove(path);
                ASSERT_EQUAL(remove_result, 0);
            } else {
                max_files--;
            }
        }
        free(namelist[n]);
    }
    free(namelist);
}

}}
