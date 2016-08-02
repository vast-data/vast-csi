/* Copyright (C) Vast Data Ltd. */

/*!
 * \file file.hpp
 * \brief The trace file encapsulates the logic of splitting a stream of traces into files.
 */
#pragma once

#include <cstdio>
#include "../execution/config.hpp"
#include "dbuffer.hpp"
#include "record.hpp"

namespace P { namespace Trace {

class TraceFile {

public:
    /*!
     * Initialize a trace file.
     *
     * \param prefix the prefix each file name will have. The suffix is auto-generated and includes a timestamp.
     * \param dir the directory to create traces in.
     * \param max_file_size the maximum file size in mega bytes.
     * \param max_files the maximum number of files. Upon rotation, if this number is reached, the oldest file is deleted.
     */
    void init(const char *prefix, const char *dir, uint32_t max_file_size, uint16_t max_files);
    void init_from_setting(const char *prefix, const char *dir, Conf::ConfigSetting *setting);
    void set_prefix(const char *prefix);
    void destroy();
    void emit(TraceRecord *record, P_DBUFFER_LENGTH_TYPE length);
    void flush();

private:
    void create_file();
    void close_file();
    void write_header();
    void write_file(void *data, size_t length);
    void rotate_chunk_if_needed(P_DBUFFER_LENGTH_TYPE length);
    void rotate_file_if_needed(P_DBUFFER_LENGTH_TYPE length);
    void delete_files_if_needed();

    const char *_dir;
    const char *_prefix;
    FILE *_file;
    uint32_t _file_offset;
    uint32_t _bytes_left_in_chunk;
    uint32_t _max_file_size;
    uint16_t _max_files;
};

}}
