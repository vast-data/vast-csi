/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dumper.hpp
 * \brief The trace dumper emits trace records from memory to files. Each channel has its own trace file.
 * The dumper starts a pthread that loops over all channels until it's explicitly stopped.
 */
#pragma once

#include <pthread.h>
#include "emitter.hpp"
#include "file.hpp"

namespace P { namespace Trace {

class Dumper {
public:

    /*!
     * Initialize a trace dumper using a configuration object, emitter and directory where traces should be saved.
     * An example configuration looks like this:
     \code
     {
         PLASMA: {
             persistent: true,
             file_size_mb: 512,
             file_count: 20
         }
     }
     \endcode
     * The values depicted in the example are the default values.
     */
    void init(Conf::ConfigSetting *setting, Emitter *emitter, const char *dir);

    /*!
     * Destroy the dumper. Must be called after stop+wait have been called.
     */
    void destroy();

    /*!
     * This function starts the pthread and returns immediately.
     */
    void start();

    /*!
     * Set a flag notifying the dumper thread to stop. Returns immediately with ensuring it actually stopped.
     */
    void stop();

    /*!
     * Wait until the pthread finished running. Should be called after p_trace_dumper_stop().
     */
    void wait();

    /*!
     * Internal function used by the pthread.
     */
    void main();
private:
    // Returns default persistence setting for the given channel.
    // TODO: currently, the default config is defined here (in code). Consider changing this so that it will be defined
    //       in a "default config" file.
    bool should_persist_channel(Channel chan) { return chan != Channel::DETAILED_DATA; }

    bool iteration(bool force);

    static const uint32_t MAX_PREFIX_SIZE = 128;

    char _file_prefixes[(int)Channel::COUNT][MAX_PREFIX_SIZE];
    DBufferReader *_readers[(int)Channel::COUNT];
    TraceFile *_files[(int)Channel::COUNT];
    uint64_t _times[(int)Channel::COUNT];
    Emitter *_emitter;
    pthread_t _pthread;
    std::atomic<bool> _stop;
    std::atomic<bool> _running;
};

}}
