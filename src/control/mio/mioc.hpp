/* Copyright (C) Vast Data Ltd. */

/*!
 * \file mioc.hpp
 * \brief MIO Control.
 */

#pragma once

#include "control/imdb/module.hpp"
#include "control/imdb/nvram.hpp"
#include "control/imdb/system.hpp"
#include "phys/mirrored_io/mio.vproto.hpp"
#include "phys/mirrored_io/mio_agent.rpc.client.hpp"

namespace Control {

class MIOControl {
public:
    // TODO(ido): currently, we use simple data structures for the section mappings. Once we get to implement
    // persistence, we should revisit this, and possibly use vproto structs instead.
    struct PhysicalAddress {
        P::GUID device_guid;
        uint64_t base_offset;
    };

    struct SectionMappings {
        PhysicalAddress mappings[MirroredIO::MAX_DEVS_PER_SECTION];
        uint8_t num_copies;
        bool in_rebuild;
    };

    void init(System *system);

    /*!
     * Calculate section mappings.
     */
    void activate();

    /*!
     * Send section mappings to the given module.
     */
    void activate_module(BaseModuleLogic *module);

    /*!
     * Add device, recalculate section mappings and update modules.
     */
    void on_device_activated(NVRAM *nvram);

    /*!
     * Remove device and update modules.
     */
    void on_device_deactivated(NVRAM *nvram);

    uint16_t get_num_sections() const { return _num_sections; }

protected:
    virtual MirroredIO::ConfigParams::RootBuilder* alloc_config();
    virtual void config_sync(BaseModuleLogic *module, MirroredIO::ConfigParams::RootBuilder *config_params);
    virtual void activate_sync(BaseModuleLogic *module);

    // All devices. This is practically the mappings for section zero.
    P::GUID _device_guids[MirroredIO::MAX_DEVS];
    uint16_t _num_devices;
    bool _section_zero_in_rebuild;

    // The first entry (section zero) isn't used (device_guids is used instead).
    SectionMappings _section_mappings[MirroredIO::MAX_SECTION_ID];
    uint16_t _num_sections;

    System *_system;
    MirroredIO::MIOAgentClient _client;
};  // class MIOControl

}  // namespace Control
