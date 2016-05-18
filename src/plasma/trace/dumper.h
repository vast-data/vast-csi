/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dumper.h
 * \brief
 */
#pragma once

#include "emitter.h"

typedef struct PTraceDumper PTraceDumper;
PTraceDumper *p_trace_dumper_init(PConfigSetting *setting, PTraceEmitter *emitter, const char *dir);
void p_trace_dumper_destroy(PTraceDumper *dumper);
void p_trace_dumper_start(PTraceDumper *dumper);
void p_trace_dumper_stop(PTraceDumper *dumper);
void p_trace_dumper_wait(PTraceDumper *dumper);
