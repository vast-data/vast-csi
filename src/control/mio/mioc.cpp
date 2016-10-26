/* Copyright (C) Vast Data Ltd. */

#include "mioc.hpp"
#include "control/imdb/dbox.hpp"
#include "control/imdb/dnode.hpp"
#include "phys/layout/section_allocator.hpp"

namespace Control {

using MirroredIO::SectionConfig;
using MirroredIO::MAX_DEVS_PER_SECTION;
using MirroredIO::MAX_DEVS;
using MirroredIO::MAX_SECTION_ID;
using MirroredIO::MAX_SECTION_CONFIGS_PER_RPC;
using P::VMsg::RpcGuard;

void MIOControl::init(System *system)
{
    _system = system;
    _client.init();
}

void MIOControl::activate()
{
    _num_devices = 0;
    _section_mappings[0].num_copies = 0;  // The first entry shouldn't be used, so just in case..
    _section_zero_in_rebuild = false;

    // We currently use a very basic algorithm for generation the section mappings. One of the assumptions is that all
    // devices have the same size, and we use device_size to assert that.
    uint64_t device_size = 0;

    IMDB_ITER_CHILDREN(_system, dbox, DBox) {
        IMDB_ITER_CHILDREN(dbox, dnode, DNode) {
            if (dnode->get_base_node()->get_state() == NodeState::ACTIVE) {
                IMDB_ITER_CHILDREN(dnode, nvram, NVRAM) {
                    ASSERT_OP(_num_devices, <, MAX_DEVS);
                    if (_num_devices == 0) {
                        device_size = nvram->get_size();
                    } else {
                        ASSERT_EQUAL(device_size, nvram->get_size());
                    }
                    _device_guids[_num_devices++] = nvram->get_guid();
                }
            }
        }
    }
    ASSERT_OP(device_size, >, 0)

    static_assert(MAX_DEVS_PER_SECTION == Layout::get_max_replication_factor_value(),
                  "MAX_DEVS_PER_SECTION should be equal to the max replication factor");
    ASSERT_OP(_num_devices, >=, Layout::get_max_replication_factor_value());

    uint64_t num_section_copies_per_device = device_size / Layout::SectionAllocator::SECTION_SIZE;
    ASSERT_OP(num_section_copies_per_device, >=, 2);  // At least one section in addition to section zero.

    // Allocate "section copy" chunks (i.e. SECTION_SIZE-sized chunks on devices) to sections. Skip the first chunk on
    // each device, because this one is saved for section zero.
    // TODO(ido): once section zero has a different size, handle it - update the calculations of:
    // 1)  num_section_copies_per_device; 2) base_offset.
    static_assert(Layout::MirroredAddress::STATIC_SECTION_ID == 0, "We rely on the fact that section zero is 0..");
    _num_sections = 1;  // Section zero.
    uint32_t mapping_idx = 0;
    _section_mappings[_num_sections].num_copies = Layout::get_replication_factor_value(
            Layout::SectionAllocator::get_section_replication_factor(_num_sections));
    _section_mappings[_num_sections].in_rebuild = false;
    for (uint64_t section_copy = 1; section_copy < num_section_copies_per_device; ++section_copy) {
        for (uint16_t device_idx = 0; device_idx < _num_devices; ++device_idx) {
            _section_mappings[_num_sections].mappings[mapping_idx].device_guid = _device_guids[device_idx];
            _section_mappings[_num_sections].mappings[mapping_idx].base_offset =
                    section_copy * Layout::SectionAllocator::SECTION_SIZE;
            ++mapping_idx;
            if (mapping_idx == _section_mappings[_num_sections].num_copies) {
                _num_sections++;
                if (_num_sections == MAX_SECTION_ID) {
                    break;
                }
                mapping_idx = 0;
                _section_mappings[_num_sections].num_copies = Layout::get_replication_factor_value(
                        Layout::SectionAllocator::get_section_replication_factor(_num_sections));
                _section_mappings[_num_sections].in_rebuild = false;
            }
        }
        if (_num_sections == MAX_SECTION_ID) {
            break;
        }
    }
    ASSERT_OP(_num_sections, >=, 2);  // At least 1 section (in addition to section zero).
}

void MIOControl::activate_module(BaseModuleLogic *module)
{
    // TODO: this function will be called in 2 contexts: 1) as part of a broad system_activate; 2) when a specific CNode
    // with a specific module is activated. In the first case, this function will be called once per (relevant) module,
    // and it's inefficient to build the RPC buffers from scratch for each module. Instead, we should do one of the
    // following: VMsg should either support the option not to free the buffer, or - better yet - support broadcasts.

    // Configure:

    // 1. Section zero:
    for (uint16_t device_idx = 0; device_idx < _num_devices; ) {
        uint16_t num_sections = (_num_devices - device_idx + MAX_DEVS_PER_SECTION - 1) / MAX_DEVS_PER_SECTION;
        if (num_sections > MAX_SECTION_CONFIGS_PER_RPC) {
            num_sections = MAX_SECTION_CONFIGS_PER_RPC;
        }
        MirroredIO::ConfigParams::RootBuilder *config_params = alloc_config();
        config_params->set_num_sections(num_sections);
        for (uint16_t section_idx = 0; section_idx < num_sections; ++section_idx) {
            SectionConfig::Builder *section_config = config_params->get_section_configs(section_idx);
            section_config->set_section_id(Layout::MirroredAddress::STATIC_SECTION_ID);
            section_config->set_in_rebuild(_section_zero_in_rebuild);
            uint16_t num_mappings = std::min((uint16_t)(_num_devices - device_idx), MAX_DEVS_PER_SECTION);
            section_config->set_num_mappings(num_mappings);
            for (uint16_t i = 0; i < num_mappings; ++i) {
                section_config->get_mappings(i)->set_device_guid(_device_guids[device_idx]);
                section_config->get_mappings(i)->set_base_offset(0);
                ++device_idx;
            }
        }
        config_sync(module, config_params);
    }

    // 2. The rest of the sections:
    for (uint16_t section_idx = 1; section_idx < _num_sections; ) {  // Skip first entry (isn't used).
        uint16_t num_sections = std::min((uint16_t)(_num_sections - section_idx), MAX_SECTION_CONFIGS_PER_RPC);
        MirroredIO::ConfigParams::RootBuilder *config_params = alloc_config();
        config_params->set_num_sections(num_sections);
        for (uint16_t config_section_idx = 0; config_section_idx < num_sections; ++config_section_idx) {
            SectionConfig::Builder *section_config = config_params->get_section_configs(config_section_idx);
            section_config->set_section_id(section_idx);
            section_config->set_in_rebuild(_section_mappings[section_idx].in_rebuild);
            uint16_t num_mappings = _section_mappings[section_idx].num_copies;
            section_config->set_num_mappings(num_mappings);
            for (uint16_t i = 0; i < num_mappings; ++i) {
                section_config->get_mappings(i)->set_device_guid(
                        _section_mappings[section_idx].mappings[i].device_guid);
                section_config->get_mappings(i)->set_base_offset(
                        _section_mappings[section_idx].mappings[i].base_offset);
            }
            ++section_idx;
        }
        config_sync(module, config_params);
    }

    // Activate:
    activate_sync(module);
}

void MIOControl::on_device_activated(UNUSED NVRAM *nvram)
{
    _device_guids[_num_devices++] = nvram->get_guid();
    /* TODO(ido): (in phase 2)
     * 1. Update the mappings according to this new device. The way to do this is stil TBD.
     * 2. Iterate over the relevant modules (i.e. IModule), and send start_rebuild for all of them, for all relevant
     * sections (including section zero).
     * 3. Send rebuild_copy to one of the agents.
     * 4. Send end_rebuild to all relevant modules for all relevant sections.
     *
     * Implementation note: remember to skip the first entry in _section_mappings.
     */
}

void MIOControl::on_device_deactivated(UNUSED NVRAM *nvram)
{
    /* TODO(ido): (in phase 2)
     * 1. Remove this device from _device_guids (and move everything to the left), update _num_devices.
     * 2. Remove this device from all sections too.
     * 3. Send remove_device to all relevant modules.
     *
     * Implementation note: remember to skip the first entry in _section_mappings.
     */
}

MirroredIO::ConfigParams::RootBuilder* MIOControl::alloc_config()
{
    return _client.alloc_config();
}

void MIOControl::config_sync(BaseModuleLogic *module, MirroredIO::ConfigParams::RootBuilder *config_params)
{
    if (_client.config_sync(module->get_address(), config_params) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure");  //TODO: unify handling of VMsg errors
    }
}

void MIOControl::activate_sync(BaseModuleLogic *module)
{
    if (_client.activate_sync(module->get_address()) != P::VMsg::VMsgRes::OK) {
        PANIC("VMsg failure");  //TODO: unify handling of VMsg errors
    }
}

} // namespace Control
