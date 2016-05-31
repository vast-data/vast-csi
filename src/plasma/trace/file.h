/* Copyright (C) Vast Data Ltd. */

/*!
 * \file file.h
 * \brief
 */
#pragma once

#include "emitter.h"
#include "p_dbuffer.h"

typedef struct PTraceFile PTraceFile;

PTraceFile *p_trace_file_init(const char *prefix, const char *dir, uint32_t max_file_size, uint16_t max_files);
PTraceFile *p_trace_file_init_from_setting(const char *prefix, const char *dir, PConfigSetting *setting);
void p_trace_file_set_prefix(PTraceFile *file, const char *prefix);
void p_trace_file_destroy(PTraceFile *trace_file);
void p_trace_file_emit(PTraceFile *trace_file, PTraceRecord *record, P_DBUFFER_LENGTH_TYPE length);
