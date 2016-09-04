/* Copyright (C) Vast Data Ltd. */

/*!
 * \file mirrored_io_agent.hpp
 * \brief
 */
#pragma once

#include "plasma/fiber/sync/rwlock.hpp"
#include "plasma/io/base_io.hpp"
#include "plasma/utils/io.hpp"

namespace MirroredIO {

struct PhysAddr {
    P::IO::BaseIO *dev;
    P::IO::Baddr byte_offset;
};

class MirroredIOAgent {
public:
    // TODO(ido): these will probably move to vproto once we implement RPCs.
    static constexpr uint32_t MAX_SECTION_ID = 16384;
    static constexpr uint32_t MAX_DEVS_PER_SECTION = 3;
    static constexpr uint32_t MAX_DEVS = 2048;  // Used for section 0.

private:
    struct SectionMappingData;

public:
    class MappingSet {
    public:
        void init(const PhysAddr *addresses, const SectionMappingData *mapping_data, bool is_reader,
                  P::IO::Baddr offset, size_t write_size = 0);
        uint8_t get_active_lock_index() const { return _active_lock_index; }
        bool get_sub_section_lock() { return _sub_section_lock; }
        void set_sub_section_lock(bool sub_section_lock) { _sub_section_lock = sub_section_lock; }

        /*!
         * Returns the size of the mapping.
         */
        P::Index size() const { return _size; }

        /*!
         * Get the address at the given index.
         *
         * may_read (if not null) will indicate whether this entry may be read. It will be true except for one case,
         * where the caller is a writer, and we're in the middle of Rebuild, and this is the last entry in the mapping,
         * and this writer is "active", i.e. has the new picture (including the newly added entry).
         */
        void at(P::Index index, PhysAddr *physical_address, bool *may_read = nullptr) const;

    private:
        bool is_active() const;

        const PhysAddr *_addresses;
        const MirroredIOAgent::SectionMappingData *_mapping_data;
        P::Index _size;
        bool _is_reader;
        P::IO::Baddr _offset;
        uint8_t _active_lock_index;
        size_t _write_size;
        bool _sub_section_lock;
    };  // class MirroredIOAgent::MappingSet

    /*!
     * Initializing the mirror mappings.
     */
    void init();

    /*!
     * Destroy the mirror mappings.
     *
     * Will (currently) be used in tests only.
     */
    void destroy();

    /*******************************
     * called from MIO_C through RPC
     *******************************/

    /* TODO(ido):
     * Add RPC functions that will call the existing functions (except for remove_device, which will be called by the DevAgent).
     * These will call the existing functions, but will first translate from dev GUID to BaseIO* (using the DevAgent).
     * Optionally, one RPC config may be translated to several config_section calls if it contains configs for more than one section.
     */

    /*!
     * Configure mappings for one section.
     *
     * Can be called more than once for one section, and mappings will be accumulated. This is probably useful only for
     * section zero.
     */
    void config_section(uint32_t section_id, const PhysAddr *addresses, P::Index num_addresses, bool in_rebuild);

    /*!
     * Switch to activated mode.
     *
     * Should be called after all configuration calls (config_section) are done.
     */
    void activate();

    /*!
     * Add a new Physical mapping to a logical section and mark the mapping as in_rebuild.
     * This means that write operations should acquire sub-section read locks while writing (avoid race with rebuild copier).
     * It also means that read operations should still avoid reading the newly added device.
     * Blocks until all ongoing write operations to the old mapping are done.
     * \param section the section being redeployed to this new device
     */
    void start_rebuild(P::IO::MirroredAddressToken section, P::IO::BaseIO *new_dev, P::IO::Baddr new_base_offset);
    /*!
     * Perform section copy operation in sub-sections.
     * This is only allowed when section is in_rebuild.
     * The operation will need to acquire a write lock.
     * Copying is done from the last device in the old mapping.
     * \param section the section being copied to the rebuilt new device
     */
    void rebuild_copy(P::IO::MirroredAddressToken section);
    /*!
     * Undo the effect of start_rebuild.
     * Unmark the section mapping as in_rebuild and return to regular state with the currently update mapping.
     * \param section the section that has finished redeployment to a new device
     */
    void end_rebuild(P::IO::MirroredAddressToken section);


    /*!
     *
     * Blocks untill all IOs to device are done (writes to section and read to device)
     * \param
     */
    void remove_section_from_device(P::IO::MirroredAddressToken section, P::IO::BaseIO *dev);

    void remove_device(P::IO::BaseIO *dev);

    /*******************************
     * called from MIO
     *******************************/
    /*!
     *
     * \param
     */
    void start_write(P::IO::MirroredAddressToken section, size_t write_size, MappingSet *phys_address_set);
    /*!
     *
     * \param
     */
    void done_write(P::IO::MirroredAddressToken section, MappingSet *phys_address_set);
    /*!
     * Get a physical address for read purposes.
     * Note: when in_rebuild last device (the one that is being rebuilt) is not a valid device to read from.
     * \param address logical address
     */
    void start_read(P::IO::MirroredAddressToken section, MappingSet *phys_address_set);
    /*!
     *
     * \param
     */
    void done_read(P::IO::MirroredAddressToken section, MappingSet *phys_address_set);

    // TODO(ido): should move to DevAgent
    // Note: this should indicate that the device is down even if it has re-entered as a newly added device
    //       meaning- a device in this context is handed a new "MirroredID" when re-entring the cluster.
    //       Another way is simply asking if this device is still in this stripe.
    bool WARN_UNUSED is_device_alive(P::IO::BaseIO *dev) const;

private:
    struct SectionMappingData {
        // Holds the number of entries in the corresponding addresses array.
        // When performing a rebuild (adding to the array), this will be updated in start_rebuild.
        // When performing a removal (deleting from the array), it will be updated when updating the array (which is the
        // last step in remove_section_from_device).
        P::Index num_addresses;

        bool in_rebuild;
        P::Index deleted_entry;  // Index of the deleted entry, if applicable. If not, this will be P::INVALID_INDEX.

        // These RWlocks allow us to have a barrier when we need to wait for all active readers/writers to exit. We have
        // 2 for readers and 2 for writers, so that when we have such a barrier we can switch between them, and then
        // wait for the current readers/writers to exit while letting new ones enter.
        P::FiberSync::RWlock readers[2];
        P::FiberSync::RWlock writers[2];

        // These indicate which ones of the RWlocks are the active ones.
        uint8_t active_readers_index;
        uint8_t active_writers_index;

        void init();
        void destroy();

        void switch_active_readers_and_writers_and_wait(bool switch_readers, bool switch_writers);

        bool check_pending_change() const { return in_rebuild || deleted_entry != P::INVALID_INDEX; }
        void set_in_rebuild(bool new_in_rebuild);
    };

    // Section mapping data.
    // Used for all sections, including section zero.
    template<uint32_t max_devs_per_section>
    struct SectionMapping {
        PhysAddr addresses[max_devs_per_section];
        SectionMappingData mapping_data;

        void init() { mapping_data.init(); }
        void destroy() { mapping_data.destroy(); }
    };  // struct MirroredIOAgent::SectionMapping

    template<uint32_t max_devs_per_section>
    void do_config_section(SectionMapping<max_devs_per_section> *section_mapping, const PhysAddr *addresses,
                           P::Index num_addresses, bool in_rebuild);
    template<uint32_t max_devs_per_section>
    void do_start_rebuild(SectionMapping<max_devs_per_section> *section_mapping, P::IO::BaseIO *new_dev,
                          P::IO::Baddr new_base_offset);
    template<uint32_t max_devs_per_section>
    void do_rebuild_copy(SectionMapping<max_devs_per_section> *section_mapping);
    template<uint32_t max_devs_per_section>
    void do_remove_section_from_device(SectionMapping<max_devs_per_section> *section_mapping, P::IO::BaseIO *dev,
                                       bool allow_not_found = false);
    template<uint32_t max_devs_per_section>
    void do_start_write(SectionMapping<max_devs_per_section> *section_mapping, uint64_t byte_offset, size_t write_size,
                        MappingSet *phys_address_set);
    void do_done_write(SectionMappingData *mapping_data, MappingSet *phys_address_set);
    template<uint32_t max_devs_per_section>
    void do_start_read(SectionMapping<max_devs_per_section> *section_mapping, uint64_t byte_offset,
                       MappingSet *phys_address_set);
    void do_done_read(SectionMappingData *mapping_data, MappingSet *phys_address_set);

    void update_max_section_id(uint32_t section_id);
    void check_section_id_valid(uint32_t section_id);

    bool _is_activated = false;

    uint32_t _max_section_id;  // max active entry index in _section_mappings
    SectionMapping<MAX_DEVS_PER_SECTION> *_section_mappings;
    SectionMapping<MAX_DEVS> _section_zero_mapping;
};  // class MirroredIOAgent

}  //  namespace MirroredIO
