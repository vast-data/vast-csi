/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dumper.h
 * \brief The trace dumper emits trace records from memory to files. Each component has its own trace file.
 * The dumper starts a pthread that loops over all components until is explicitly stopped.
 */
#pragma once

#include "emitter.h"

typedef struct PTraceDumper PTraceDumper;

/*!
 * Initialize a trace dumper using a configuration object, emitter and directory where traces should be saved.
 * An example configuration looks like this:
\code
{
  COMPONENT_PLASMA: {
    min_severity: "P_TRACE_DEBUG",
    buffer_size_mb: 8,
    persistent: true,
    file_size_mb: 512,
    file_count: 20
  }
}
\endcode
 * The values depicted in the example are the default values.
 */
PTraceDumper *p_trace_dumper_init(PConfigSetting *setting, PTraceEmitter *emitter, const char *dir);

/*!
 * Destroy the dumper. Must be called after stop+wait have been called.
 */
void p_trace_dumper_destroy(PTraceDumper *dumper);

/*!
 * This function starts the pthread and returns immediately.
 */
void p_trace_dumper_start(PTraceDumper *dumper);

/*!
 * Set a flag notifying the dumper thread to stop. Returns immediately with ensuring it actually stopped.
 */
void p_trace_dumper_stop(PTraceDumper *dumper);

/*!
 * Wait until the pthread finished running. Should be called after p_trace_dumper_stop().
 */
void p_trace_dumper_wait(PTraceDumper *dumper);
