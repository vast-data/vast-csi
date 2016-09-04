#include "mirrored_io_agent.hpp"

namespace {

static void flush_rwlock(P::FiberSync::RWlock* rwlock)
{
    rwlock->lock_write();
    rwlock->unlock();
}

}  // namespace

namespace MirroredIO {

void MirroredIOAgent::MappingSet::init(const PhysAddr *addresses, const SectionMappingData *mapping_data,
                                       bool is_reader, P::IO::Baddr offset, size_t write_size /* = 0 */)
{
    ASSERT_NOT_NULL(addresses);
    ASSERT_NOT_NULL(mapping_data);
    _addresses = addresses;
    _mapping_data = mapping_data;
    _is_reader = is_reader;
    _offset = offset;
    _size = _mapping_data->num_addresses;
    _write_size = write_size;
    _sub_section_lock = false;
    if (is_reader) {
        _active_lock_index = _mapping_data->active_readers_index;
        if (_mapping_data->check_pending_change()) {
            --_size;
        }
    } else {  // writer
        _active_lock_index = _mapping_data->active_writers_index;
        if (_mapping_data->deleted_entry != P::INVALID_INDEX) {
            --_size;
        }
    }
}

void MirroredIOAgent::MappingSet::at(P::Index index, PhysAddr *physical_address, bool *may_read) const
{
    ASSERT_NOT_NULL(physical_address);
    ASSERT_OP(index, <, _size);
    if (is_active() && _mapping_data->deleted_entry != P::INVALID_INDEX && index >= _mapping_data->deleted_entry) {
        ++index;
    }
    *physical_address = _addresses[index];
    physical_address->byte_offset += _offset;
    if (may_read != nullptr) {
        if (!_is_reader && index == _size - 1 && _mapping_data->in_rebuild && is_active()) {
            *may_read = false;
        } else {
            *may_read = true;
        }
    }
}

bool MirroredIOAgent::MappingSet::is_active() const
{
    if (_is_reader) {
        return _active_lock_index == _mapping_data->active_readers_index;
    } else {  // writer
        return _active_lock_index == _mapping_data->active_writers_index;
    }
}

void MirroredIOAgent::SectionMappingData::init()
{
    num_addresses = 0;
    in_rebuild = false;
    deleted_entry = P::INVALID_INDEX;
    readers[0].init();
    readers[1].init();
    writers[0].init();
    writers[1].init();
    active_readers_index = 0;
    active_writers_index = 0;
}

void MirroredIOAgent::SectionMappingData::destroy()
{
    readers[0].destroy();
    readers[1].destroy();
    writers[0].destroy();
    writers[1].destroy();
}

void MirroredIOAgent::SectionMappingData::switch_active_readers_and_writers_and_wait(bool switch_readers,
                                                                                     bool switch_writers)
{
    // Make sure the new one is available:
    if (readers) {
        ASSERT(!readers[1 - active_readers_index].is_locked());
    }
    if (writers) {
        ASSERT(!writers[1 - active_writers_index].is_locked());
    }

    // Switch active:
    if (readers) {
        active_readers_index = 1 - active_readers_index;
    }
    if (writers) {
        active_writers_index = 1 - active_writers_index;
    }

    // Wait for old ones to exit:
    if (readers) {
        flush_rwlock(&readers[1 - active_readers_index]);
    }
    if (writers) {
        flush_rwlock(&writers[1 - active_writers_index]);
    }
}

void MirroredIOAgent::SectionMappingData::set_in_rebuild(bool new_in_rebuild)
{
    ASSERT(in_rebuild == !new_in_rebuild);
    in_rebuild = new_in_rebuild;
}

void MirroredIOAgent::init()
{
    _is_activated = false;
    _max_section_id = 0;

    _section_mappings = new SectionMapping<MAX_DEVS_PER_SECTION>[MAX_SECTION_ID];

    for (uint32_t i = 0; i < MAX_SECTION_ID; ++i) {
        _section_mappings[i].init();
    }
    _section_zero_mapping.init();
}

void MirroredIOAgent::destroy()
{
    for (uint32_t i = 0; i < MAX_SECTION_ID; ++i) {
        _section_mappings[i].destroy();
    }

    delete[] _section_mappings;
    _section_zero_mapping.destroy();
}

void MirroredIOAgent::config_section(uint32_t section_id, const PhysAddr *addresses, P::Index num_addresses,
                                     bool in_rebuild)
{
    ASSERT(!_is_activated);
    ASSERT_OP(section_id, <, MAX_SECTION_ID);
    if (section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_config_section(&_section_zero_mapping, addresses, num_addresses, in_rebuild);
    } else {
        update_max_section_id(section_id);
        do_config_section(&_section_mappings[section_id], addresses, num_addresses, in_rebuild);
    }
}

template<uint32_t max_devs_per_section>
void MirroredIOAgent::do_config_section(SectionMapping<max_devs_per_section> *section_mapping,
                                        const PhysAddr *addresses, P::Index num_addresses, bool in_rebuild)
{
    P::Index new_num_addresses = section_mapping->mapping_data.num_addresses + num_addresses;
    ASSERT_OP(new_num_addresses, <=, max_devs_per_section);

    for (P::Index i = 0; i < num_addresses; ++i) {
        section_mapping->addresses[section_mapping->mapping_data.num_addresses + i] = addresses[i];
    }
    section_mapping->mapping_data.in_rebuild = in_rebuild;
    section_mapping->mapping_data.num_addresses = new_num_addresses;
}

void MirroredIOAgent::activate()
{
    ASSERT(!_is_activated);
    _is_activated = true;
}

void MirroredIOAgent::start_rebuild(P::IO::MirroredAddressToken section, P::IO::BaseIO *new_dev,
                                    P::IO::Baddr new_base_offset)
{
    ASSERT(_is_activated);
    ASSERT_OP(section.section_id, <, MAX_SECTION_ID);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_start_rebuild(&_section_zero_mapping, new_dev, new_base_offset);
    } else {
        update_max_section_id(section.section_id);
        do_start_rebuild(&_section_mappings[section.section_id], new_dev, new_base_offset);
    }
}

template<uint32_t max_devs_per_section>
void MirroredIOAgent::do_start_rebuild(SectionMapping<max_devs_per_section> *section_mapping, P::IO::BaseIO *new_dev,
                                       P::IO::Baddr new_base_offset)
{
    ASSERT(!section_mapping->mapping_data.check_pending_change());
    section_mapping->mapping_data.set_in_rebuild(true);
    ASSERT_OP(section_mapping->mapping_data.num_addresses, <, max_devs_per_section);
    section_mapping->addresses[section_mapping->mapping_data.num_addresses].dev = new_dev;
    section_mapping->addresses[section_mapping->mapping_data.num_addresses].byte_offset = new_base_offset;
    ++section_mapping->mapping_data.num_addresses;
    section_mapping->mapping_data.switch_active_readers_and_writers_and_wait(false /* switch_readers */,
                                                                             true /* switch_writers */);
}

void MirroredIOAgent::end_rebuild(P::IO::MirroredAddressToken section)
{
    ASSERT(_is_activated);
    ASSERT_OP(section.section_id, <, MAX_SECTION_ID);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        _section_zero_mapping.mapping_data.set_in_rebuild(false);
    } else {
        _section_mappings[section.section_id].mapping_data.set_in_rebuild(false);
    }
}

void MirroredIOAgent::rebuild_copy(P::IO::MirroredAddressToken section)
{
    ASSERT(_is_activated);
    ASSERT_OP(section.section_id, <, MAX_SECTION_ID);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_rebuild_copy(&_section_zero_mapping);
    } else {
        do_rebuild_copy(&_section_mappings[section.section_id]);
    }
}

template<uint32_t max_devs_per_section>
void MirroredIOAgent::do_rebuild_copy(SectionMapping<max_devs_per_section> *section_mapping)
{
    ASSERT(section_mapping->mapping_data.in_rebuild);
    /* TODO(ido):
     * Iterate over all sub-sections of the given section.
     *   The sub-section size should be a const. The section size should also be a const for now.
     * For each sub-section, take a write lock (using RPC), perform copy, and then release the write lock.
     *   Copying is done from the last device in the old mapping.
     *   Copy using BaseIO::read and BaseIO::write.
     *   the sub-section rwlocks aren't persistent. We should later discuss how to handle their failure. Should we support abort_rebuild?
     */
}

void MirroredIOAgent::remove_section_from_device(P::IO::MirroredAddressToken section, P::IO::BaseIO *dev)
{
    ASSERT(_is_activated);
    ASSERT_OP(section.section_id, <, MAX_SECTION_ID);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_remove_section_from_device(&_section_zero_mapping, dev);
    } else {
        do_remove_section_from_device(&_section_mappings[section.section_id], dev);
    }
}

template<uint32_t max_devs_per_section>
void MirroredIOAgent::do_remove_section_from_device(SectionMapping<max_devs_per_section> *section_mapping,
                                                    P::IO::BaseIO *dev, bool allow_not_found /* = false */)
{
    ASSERT(!section_mapping->mapping_data.check_pending_change());
    P::Index dev_index = P::INVALID_INDEX;
    for (P::Index i = 0; i < section_mapping->mapping_data.num_addresses; ++i) {
        if (section_mapping->addresses[i].dev == dev) {
            dev_index = i;
            break;
        }
    }
    if (dev_index == P::INVALID_INDEX) {
        ASSERT(allow_not_found);
        return;
    }
    section_mapping->mapping_data.deleted_entry = dev_index;

    section_mapping->mapping_data.switch_active_readers_and_writers_and_wait(true /* switch_readers */,
                                                                             true /* switch_writers */);

    --section_mapping->mapping_data.num_addresses;
    for (P::Index i = section_mapping->mapping_data.deleted_entry; i < section_mapping->mapping_data.num_addresses;
         ++i) {
        section_mapping->addresses[i] = section_mapping->addresses[i + 1];
    }
    section_mapping->mapping_data.deleted_entry = P::INVALID_INDEX;
}

void MirroredIOAgent::remove_device(P::IO::BaseIO *dev)
{
    ASSERT(_is_activated);
    do_remove_section_from_device(&_section_zero_mapping, dev);
    for (uint32_t i = 1; i <= _max_section_id; ++i) {  // We skip 0
        do_remove_section_from_device(&_section_mappings[i], dev, true /* allow_not_found */);
    }
}

void MirroredIOAgent::start_write(P::IO::MirroredAddressToken section, size_t write_size, MappingSet *phys_address_set)
{
    ASSERT(_is_activated);
    ASSERT_NOT_NULL(phys_address_set);
    check_section_id_valid(section.section_id);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_start_write(&_section_zero_mapping, section.byte_offset, write_size, phys_address_set);
    } else {
        do_start_write(&_section_mappings[section.section_id], section.byte_offset, write_size, phys_address_set);
    }
}

template<uint32_t max_devs_per_section>
void MirroredIOAgent::do_start_write(SectionMapping<max_devs_per_section> *section_mapping, uint64_t byte_offset,
                                     size_t write_size, MappingSet *phys_address_set)
{
    phys_address_set->init(section_mapping->addresses, &section_mapping->mapping_data, false /* is_reader */,
                           byte_offset, write_size);
    section_mapping->mapping_data.writers[phys_address_set->get_active_lock_index()].lock_read();
    if (section_mapping->mapping_data.in_rebuild) {
        ASSERT(!phys_address_set->get_sub_section_lock());
        phys_address_set->set_sub_section_lock(true);
        /* TODO(ido):
         * Iterate over all relevant sub-sections (according to the physical offset and write_size.
         * For each sub-section, acquire read-lock (using RPC).
         */
    }
}

void MirroredIOAgent::done_write(P::IO::MirroredAddressToken section, MappingSet *phys_address_set)
{
    ASSERT(_is_activated);
    ASSERT_NOT_NULL(phys_address_set);
    check_section_id_valid(section.section_id);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_done_write(&_section_zero_mapping.mapping_data, phys_address_set);
    } else {
        do_done_write(&_section_mappings[section.section_id].mapping_data, phys_address_set);
    }
}

void MirroredIOAgent::do_done_write(SectionMappingData *mapping_data, MappingSet *phys_address_set)
{
    if (phys_address_set->get_sub_section_lock()) {
        phys_address_set->set_sub_section_lock(false);
        /* TODO(ido):
         * Iterate over all relevant sub-sections (according to the physical offset and phys_address_set->_write_size.
         * For each sub-section, unlock (using RPC).
         */
    }
    mapping_data->writers[phys_address_set->get_active_lock_index()].unlock();
}

void MirroredIOAgent::start_read(P::IO::MirroredAddressToken section, MappingSet *phys_address_set)
{
    ASSERT(_is_activated);
    ASSERT_NOT_NULL(phys_address_set);
    check_section_id_valid(section.section_id);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_start_read(&_section_zero_mapping, section.byte_offset, phys_address_set);
    } else {
        do_start_read(&_section_mappings[section.section_id], section.byte_offset, phys_address_set);
    }
}

template<uint32_t max_devs_per_section>
void MirroredIOAgent::do_start_read(SectionMapping<max_devs_per_section> *section_mapping, uint64_t byte_offset,
                                    MappingSet *phys_address_set)
{
    phys_address_set->init(section_mapping->addresses, &section_mapping->mapping_data, true /* is_reader */,
                           byte_offset);
    section_mapping->mapping_data.readers[phys_address_set->get_active_lock_index()].lock_read();
}

void MirroredIOAgent::done_read(P::IO::MirroredAddressToken section, MappingSet *phys_address_set)
{
    ASSERT(_is_activated);
    ASSERT_NOT_NULL(phys_address_set);
    check_section_id_valid(section.section_id);
    if (section.section_id == P::IO::MirroredAddressToken::STATIC_SECTION_ID) {
        do_done_read(&_section_zero_mapping.mapping_data, phys_address_set);
    } else {
        do_done_read(&_section_mappings[section.section_id].mapping_data, phys_address_set);
    }
}

void MirroredIOAgent::do_done_read(SectionMappingData *mapping_data, MappingSet *phys_address_set)
{
    mapping_data->readers[phys_address_set->get_active_lock_index()].unlock();
}

void MirroredIOAgent::update_max_section_id(uint32_t section_id)
{
    if (section_id > _max_section_id) {
        _max_section_id = section_id;
    }
}
void MirroredIOAgent::check_section_id_valid(uint32_t section_id)
{
    ASSERT_OP(section_id, <=, _max_section_id);
}

bool MirroredIOAgent::is_device_alive(P::IO::BaseIO *dev) const
{
    // TODO: implement
//    PANIC("Not implemented!");
    return true;
}

}  // namespace MirroredIO
