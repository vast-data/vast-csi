/* Copyright (C) Vast Data Ltd. */

/*!
 * \file file.h
 * \brief The trace file encapsulates the logic of splitting a stream of traces into files.
 */
#pragma once

#include "emitter.h"
#include "p_dbuffer.h"

typedef struct PTraceFile PTraceFile;

/*!
 * Initialize a trace file.
 *
 * \param prefix the prefix each file name will have. The suffix is auto-generated and includes a timestamp.
 * \param dir the directory to create traces in.
 * \param max_file_size the maximum file size in mega bytes.
 * \param max_files the maximum number of files. Upon rotation, if this number is reached, the oldest file is deleted.
 */
PTraceFile *p_trace_file_init(const char *prefix, const char *dir, uint32_t max_file_size, uint16_t max_files);
PTraceFile *p_trace_file_init_from_setting(const char *prefix, const char *dir, PConfigSetting *setting);
void p_trace_file_set_prefix(PTraceFile *file, const char *prefix);
void p_trace_file_destroy(PTraceFile *trace_file);
void p_trace_file_emit(PTraceFile *trace_file, PTraceRecord *record, P_DBUFFER_LENGTH_TYPE length);
