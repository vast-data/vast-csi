/* Copyright (C) Vast Data Ltd. */
#include "dumper.hpp"

#include <pthread.h>
#include <unistd.h>
#include <plasma/internal.hpp>

#include "../utils/os.hpp"
#include "../utils/macros.hpp"
#include "../utils/assert.hpp"
#include "../execution/config.hpp"

using namespace P::Conf;

namespace P { namespace Trace {

void Dumper::init(ConfigSetting *setting, Emitter *emitter, const char *dir)
{
    ensure_directory_exists(dir);

    _stop = false;
    _running = false;
    _emitter = emitter;

    bool configured[(byte)Channel::COUNT];
    LOOP(Channel::COUNT, i) {
        _readers[i] = new DBufferReader;
        _readers[i]->init(emitter->get_dbuffer((Channel)i));

        _files[i] = nullptr;
        _times[i] = 0;

        configured[i] = false;
    }

    if (setting != nullptr) {
        ConfigSetting *channels_setting = conf_setting_lookup_optional(setting, "channels");
        if (channels_setting != nullptr) {
            LOOP(conf_setting_length(channels_setting), i) {
                ConfigSetting *chan_setting = conf_setting_get_element(channels_setting, (uint32_t) i);
                const char *chan_name = conf_setting_name(chan_setting);
                Channel chan_id = channel_from_string(chan_name);

                configured[(byte)chan_id] = true;

                bool persistent = should_persist_channel(chan_id);
                ConfigSetting *persistent_setting = conf_setting_lookup_optional(chan_setting, "persistent");
                if (persistent_setting != nullptr) {
                    persistent = conf_setting_get_bool(persistent_setting);
                }

                if (!persistent)
                    continue;

                _files[(byte)chan_id] = new TraceFile;
                _files[(byte)chan_id]->init_from_setting(nullptr, dir, chan_setting);
            }
        }
    }
    LOOP(Channel::COUNT, i) {
        if (!configured[i] && should_persist_channel((Channel)i)) {
            _files[i] = new TraceFile;
            _files[i]->init_from_setting(nullptr, dir, nullptr);
        }
    }
}

void Dumper::destroy()
{
    ASSERT(!_running);
    LOOP(Channel::COUNT, i) {
        if (_readers[i] != nullptr) {
            delete _readers[i];
            if (_files[i] != nullptr) {
                _files[i]->destroy();
                delete _files[i];
            }
        }
    }
}

bool Dumper::iteration(bool force)
{
    static TraceInfo TRACE_SECTION overflow_info = {
        CURRENT_COMPONENT, "Trace overflow. %hd buffers lost.", __FILE__, __LINE__, __func__
    };
    uint16_t overflow_index = get_trace_info_index(&overflow_info);

    TraceRecord record;
    P_DBUFFER_LENGTH_TYPE length;
    bool found = false;
    LOOP(Channel::COUNT, i) {
        if (_files[i] != nullptr) {
            // TODO: improve performance by flushing whole buffers instead of iterating over records.
            auto read_result = _readers[i]->read(&record, &length, force);
            switch (read_result) {
            case DBufferReader::ReadResult::NOTHING:
                break;
            case DBufferReader::ReadResult::NEXT:
                found = true;
                break;
            case DBufferReader::ReadResult::SUCCESS:
                _times[i] = record.time;
                _files[i]->emit(&record, length);
                found = true;
                break;
            case DBufferReader::ReadResult::OVERFLOW:
                found = true;
                // set the time of the last record emitted for this channel.
                // the reader expects timestamps to be monotonically increasing (does a merge sort).
                record.time = _times[i];
                record.job_id = 0; // no fiber
                record.severity = Severity::ERROR;
                record.info_index = overflow_index;
                uint32_t large_length = length; // temporary workaround for ORION-35
                memcpy(record.params, &large_length, P_MAX(sizeof(large_length), 4));
                _files[i]->emit(&record, offsetof(TraceRecord, params) + sizeof(large_length));
                break;
            }
        }
    }
    return found;
}

void *dumper_main(void *dumper_arg) {
    Dumper *dumper = (Dumper*) dumper_arg;
    dumper->main();
    return nullptr;
}

#define IDLE_SLEEP_MICROS 10
void Dumper::main()
{
    _running = true;
    while (!_stop) {
        if (!iteration(false)) {
            LOOP(Channel::COUNT, i) {
                if (_files[i] == nullptr) {
                    continue;
                }
                _files[i]->flush();
            }
            usleep(IDLE_SLEEP_MICROS);
        }
    }
    while (iteration(true)) {

    }
    _running = false;
}

#include <sys/syscall.h>

void Dumper::start()
{
    ASSERT(!_running);
    _stop = false;

    LOOP(Channel::COUNT, i) {
        if (_files[i] == nullptr) {
            continue;
        }
        _running = true;
        const char *channel = channel_to_string((Channel) i);
        snprintf(_file_prefixes[i], MAX_PREFIX_SIZE, "%s.%ld", channel, syscall(SYS_gettid));
        _files[i]->set_prefix(_file_prefixes[i]);
    }

    ASSERT_EQUAL(pthread_create(&_pthread, nullptr, dumper_main, this), 0);
}

void Dumper::stop()
{
    _stop = true;
}

#define WAIT_SLEEP_MICROS 100
void Dumper::wait()
{
    while (_running)
        usleep(WAIT_SLEEP_MICROS);
}

}}
