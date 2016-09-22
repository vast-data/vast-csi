/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <signal.h>
#include "plasma/trace/emitter.hpp"
#include "plasma/trace/file.hpp"
#include "plasma/trace/dumper.hpp"
#include "plasma/utils/backtrace.hpp"

namespace Test {

static P::Trace::Dumper dumper;
static bool traces_initialized = false;

static __attribute__ ((destructor)) void finalize_traces()
{
    if (traces_initialized) {
        dumper.stop();
        dumper.wait();
    }
}

void error_handler(int sig)
{
    P::Backtracer::show_backtrace();
    finalize_traces();
    exit(sig);
}

void init_traces()
{

    if (traces_initialized)
        return;
    traces_initialized = true;

    static P::Trace::Emitter emitter;
    emitter.init(nullptr, true);

    dumper.init(nullptr, &emitter, "data/traces");

    emitter.set_local();
    emitter.set_global();
    dumper.start();

    signal(SIGSEGV, error_handler);
    signal(SIGABRT, error_handler);
    signal(SIGTERM, error_handler);
    signal(SIGINT, error_handler);
}

}
