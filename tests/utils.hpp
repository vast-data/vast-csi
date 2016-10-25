/* Copyright (C) Vast Data Ltd. */
#pragma once

#include <signal.h>
#include "plasma/execution/config_internal.hpp"
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

NO_RETURN static void error_handler(int sig)
{
    printf("===ERROR SIGNAL (%s)===\n", strsignal(sig));
    P::Backtracer::show_backtrace();
    finalize_traces();
    exit(sig);
}

static char config_string[] = QUOTE(traces: {
    channels: {
        DATA: {
            buffer_size_mb: 1,
            persistent: true,
            file_size_mb: 2,
            file_count: 10
        }
    }
    components: {
        PLASMA: {
            min_severity: "_DEBUG"
        }
        ESTORE: {
            min_severity: "_DEBUG"
        }
        TEST: {
            min_severity: "_DEBUG"
        }
        NFS: {
            min_severity: "_DEBUG"
        }
    }
    });

static void init_traces()
{
    if (traces_initialized)
        return;
    traces_initialized = true;

    P::Conf::Config* conf = P::Conf::conf_init();
    ASSERT_EQ(P::Conf::conf_read_string(conf, config_string), true);
    P::Conf::ConfigSetting *setting = P::Conf::conf_lookup(conf, "traces");
    static P::Trace::Emitter emitter;
    emitter.init(setting, true);

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
