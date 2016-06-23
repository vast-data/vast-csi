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

DBuffer *Emitter::get_dbuffer(ComponentId component)
{
    return _buffers[(byte) component];
}

uint64_t Emitter::get_fiber_id()
{
    Fiber *fiber = Fiber::get_current();
    if (fiber != nullptr)
        return fiber->get_job_id();
    else
        return 0; // trace records emitted before running within a scheduler
}

const byte BUFFER_COUNT = 4;
const byte DEFAULT_BUF_SIZE_MB = 8;

void Emitter::init(ConfigSetting *setting, bool shared)
{
    // start off with all components disabled (indicated by maximal severity).
    LOOP(ComponentId::COUNT, i) {
        _min_severity[i] = Severity::SEVERITY_COUNT;
        _buffers[i] = nullptr;
    }

    if (shared) {
        _lock = new Sync::SpinLock();
        _lock->init();
    } else {
        _lock = nullptr;
    }

    if (setting == nullptr)
        return;

    LOOP(conf_setting_length(setting), i) {
        ConfigSetting *comp_setting = conf_setting_get_element(setting, (uint32_t) i);
        const char *comp_name = conf_setting_name(comp_setting);
        byte comp_id = (byte) component_id_from_string(comp_name);

        ConfigSetting *buf_size_setting = conf_setting_lookup_optional(comp_setting, "buffer_size_mb");
        uint32_t buf_size = DEFAULT_BUF_SIZE_MB;
        if (buf_size_setting != nullptr)
            buf_size = (uint32_t) conf_setting_get_int32(buf_size_setting);
        _buffers[comp_id] = new DBuffer();
        _buffers[comp_id]->init(BUFFER_COUNT, buf_size * UNIT_MiB);

        ConfigSetting *min_severity_setting = conf_setting_lookup_optional(comp_setting, "min_severity");
        Severity min_severity = Severity::SEVERITY_DEBUG;
        if (min_severity_setting != nullptr)
            min_severity = severity_from_string(conf_setting_get_string(min_severity_setting));
        _min_severity[comp_id] = min_severity;
    }
}

void Emitter::destroy()
{
    LOOP(ComponentId::COUNT, i) {
        if (_buffers[i] != nullptr) {
            _buffers[i]->destroy();
            delete _buffers[i];
        }
    }
    _lock->destroy();
    delete _lock;
}

}}
