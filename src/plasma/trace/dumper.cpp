/* Copyright (C) Vast Data Ltd. */
#include "dumper.hpp"

#include <pthread.h>
#include <unistd.h>

#include "../utils/os.hpp"
#include "../utils/macros.hpp"
#include "../utils/assert.hpp"
#include "../execution/config.hpp"

using namespace P::Conf;

namespace P { namespace Trace {

#define DEFAULT_PERSISTENT (true)
void Dumper::init(ConfigSetting *setting, Emitter *emitter, const char *dir)
{
    ensure_directory_exists(dir);

    _stop = false;
    _running = false;
    _emitter = emitter;

    LOOP((byte)ComponentId::COUNT, i) {
        _readers[(byte)i] = nullptr;
        _files[(byte)i] = nullptr;
        _times[(byte)i] = 0;
    }

    LOOP(conf_setting_length(setting), i) {
        ConfigSetting *comp_setting = conf_setting_get_element(setting, (uint32_t) i);
        const char *comp_name = conf_setting_name(comp_setting);
        ComponentId comp_id = component_id_from_string(comp_name);

        _readers[(byte)comp_id] = new DBufferReader();
        _readers[(byte)comp_id]->init(emitter->get_dbuffer(comp_id));

        ConfigSetting *persistent_setting = conf_setting_lookup_optional(comp_setting, "persistent");
        bool persistent = DEFAULT_PERSISTENT;
        if (persistent_setting != nullptr)
            persistent = conf_setting_get_bool(persistent_setting);

        if (!persistent)
            continue;

        _files[(byte)comp_id] = new TraceFile();
        _files[(byte)comp_id]->init_from_setting(nullptr, dir, comp_setting);
    }
}

void Dumper::destroy()
{
    ASSERT(!_running);
    LOOP((byte)ComponentId::COUNT, i) {
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
        "Trace overflow. %hd buffers lost.", __FILE__, "<temp>", __LINE__, __func__
    };
    uint16_t overflow_index = get_trace_info_index(&overflow_info);

    TraceRecord record;
    P_DBUFFER_LENGTH_TYPE length;
    bool found = false;
    LOOP((byte)ComponentId::COUNT, i) {
        if (_files[i] != nullptr) {
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
                // set the time of the last record emitted for this component.
                // the reader expects timestamps to be monotonically increasing (does a merge sort).
                record.time = _times[i];
                record.job_id = 0; // no fiber
                record.severity = Severity::SEVERITY_ERROR;
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
            LOOP((byte)ComponentId::COUNT, i) {
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

    LOOP((byte)ComponentId::COUNT, i) {
        if (_files[i] == nullptr) {
            continue;
        }
        _running = true;
        const char *comp = component_id_to_string((ComponentId) i);
        snprintf(_file_prefixes[i], MAX_PREFIX_SIZE, "%s.%ld", comp, syscall(SYS_gettid));
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
