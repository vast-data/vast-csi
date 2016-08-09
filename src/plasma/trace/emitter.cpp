/* Copyright (C) Vast Data Ltd. */
#include "emitter.hpp"
#include "../execution/config.hpp"
#include "../utils/units.hpp"
#include "../fiber/fiber.hpp"

using namespace P::Conf;

namespace P { namespace Trace {

thread_local Emitter *Emitter::_local_emitter = nullptr;
Emitter *Emitter::_global_emitter = nullptr;

void Emitter::set_local()
{
    _local_emitter = this;
}

void Emitter::set_global()
{
    _global_emitter = this;
}

DBuffer *Emitter::get_dbuffer(Channel channel)
{
    return _buffers[(byte) channel];
}

uint64_t Emitter::get_fiber_id()
{
    Fiber *fiber = Fiber::get_current();
    if (fiber != nullptr)
        return fiber->get_job_id();
    else
        return 0; // trace records emitted before running within a scheduler
}

void Emitter::flush()
{
    LOOP(Channel::COUNT, i) {
        if (_buffers[i] != nullptr)
            _buffers[i]->flush();
    }
}

const byte BUFFER_COUNT = 4;
const byte DEFAULT_BUF_SIZE_MB = 8;

void Emitter::init(ConfigSetting *setting, bool shared)
{
    if (shared) {
        _lock = new Sync::SpinLock();
        _lock->init();
    } else {
        _lock = nullptr;
    }

    ConfigSetting *channels_setting = nullptr;
    ConfigSetting *components_setting = nullptr;
    if (setting != nullptr) {
        channels_setting = conf_setting_lookup_optional(setting, "channels");
        components_setting = conf_setting_lookup_optional(setting, "components");
    }

    LOOP (Channel::COUNT, i) {
        _buffers[i] = nullptr;
    }

    if (channels_setting != nullptr) {
        LOOP(conf_setting_length(channels_setting), i) {
            ConfigSetting *chan_setting = conf_setting_get_element(channels_setting, (uint32_t) i);
            const char *chan_name = conf_setting_name(chan_setting);
            byte chan_id = (byte) channel_from_string(chan_name);

            ConfigSetting *buf_size_setting = conf_setting_lookup_optional(chan_setting, "buffer_size_mb");
            if (buf_size_setting != nullptr) {
                ASSERT(_buffers[chan_id] == nullptr);
                _buffers[chan_id] = new DBuffer;
                _buffers[chan_id]->init(BUFFER_COUNT, (uint32_t) conf_setting_get_int32(buf_size_setting) * UNIT_MiB);
            }
        }
    }
    LOOP (Channel::COUNT, i) {
        if (_buffers[i] == nullptr) {
            _buffers[i] = new DBuffer;
            _buffers[i]->init(BUFFER_COUNT, DEFAULT_BUF_SIZE_MB * UNIT_MiB);
        }
    }

    LOOP(ComponentId::COUNT, i) {
#ifdef DEBUG
        _min_severity[i] = Severity::_DEBUG;
#else
        _min_severity[i] = Severity::INFO;
#endif
    }

    if (components_setting != nullptr) {
        LOOP(conf_setting_length(components_setting), i) {
            ConfigSetting *comp_setting = conf_setting_get_element(components_setting, (uint32_t) i);
            const char *comp_name = conf_setting_name(comp_setting);
            byte comp_id = (byte) component_id_from_string(comp_name);

            ConfigSetting *min_severity_setting = conf_setting_lookup_optional(comp_setting, "min_severity");
            if (min_severity_setting != nullptr) {
                _min_severity[comp_id] = severity_from_string(conf_setting_get_string(min_severity_setting));
            }
        }
    }
}

void Emitter::destroy()
{
    LOOP(Channel::COUNT, i) {
        if (_buffers[i] != nullptr) {
            _buffers[i]->destroy();
            delete _buffers[i];
        }
    }
    _lock->destroy();
    delete _lock;
}

}}
