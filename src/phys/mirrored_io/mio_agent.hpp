/* Copyright (C) Vast Data Ltd. */

/*!
 * \file mio_agent.hpp
 * \brief
 */
#pragma once

#include "mio_agent.rpc.server.hpp"
#include "control/dev_agent/dev_agent.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/fiber/sync/rwlock.hpp"
#include "plasma/io/base_io.hpp"
#include "plasma/utils/io.hpp"

namespace MirroredIO {

struct PhysAddr {
    P::IO::BaseIO *dev;
    P::IO::Baddr byte_offset;
};

class MIOAgent : public MIOAgentServer {
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
        const MIOAgent::SectionMappingData *_mapping_data;
        P::Index _size;
        bool _is_reader;
        P::IO::Baddr _offset;
        uint8_t _active_lock_index;
        size_t _write_size;
        bool _sub_section_lock;
    };  // class MIOAgent::MappingSet

    /*!
     * Initializing the mirror mappings.
     */
    void init(P::SiloId silo_id, ModuleId module_id, P::Index fiber_group_id, Control::DevAgent *dev_agent);

    /*!
     * Destroy the mirror mappings.
     */
    void destroy();

    /*******************************
     * called from MIO_C through RPC
     *******************************/

    /*!
     * Configure section mappings.
     *
     * Can be called more than once, including with the same section ID, and mappings will be accumulated. This is
     * probably useful only for section zero.
     */
    virtual void config(ConfigParams::RootReader *args, P::VProto::Empty::RootBuilder *res);

    /*!
     * Switch to activated mode.
     *
     * Should be called after all configuration calls (config) are done.
     */
    virtual void activate(P::VProto::Empty::RootReader *args, P::VProto::Empty::RootBuilder *res);

    virtual void start_rebuilds(StartRebuildsParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    virtual void end_rebuilds(EndRebuildsParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    virtual void rebuild_copy(RebuildCopyParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    virtual void remove_mappings(RemoveMappingsParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    virtual void remove_device(RemoveDeviceParams::RootReader *args, P::VProto::Empty::RootBuilder *res);

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
    };  // struct MIOAgent::SectionMapping


    /***************************************************
     * Helper functions, used to implement the RPC calls
     ***************************************************/

// TODO(ido): config_section is public just for test_mio. Remove it (and the correspending "private" below) once that
// test is fixed. See ORION-81.
public:
    /*!
     * Configure mappings for one section.
     *
     * Can be called more than once for one section, and mappings will be accumulated. This is probably useful only for
     * section zero.
     */
    void config_section(uint32_t section_id, const PhysAddr *addresses, P::Index num_addresses, bool in_rebuild);
private:

    /*!
     * Add a new Physical mapping to a logical section and mark the mapping as in_rebuild.
     * This means that write operations should acquire sub-section read locks while writing (avoid race with rebuild copier).
     * It also means that read operations should still avoid reading the newly added device.
     * Blocks until all ongoing write operations to the old mapping are done.
     * \param section the section being redeployed to this new device
     */
    void start_rebuild(uint32_t section_id, P::IO::BaseIO *new_dev, P::IO::Baddr new_base_offset);
    /*!
     * Perform section copy operation in sub-sections.
     * This is only allowed when section is in_rebuild.
     * The operation will need to acquire a write lock.
     * Copying is done from the last device in the old mapping.
     * \param section the section being copied to the rebuilt new device
     */
    void rebuild_copy_internal(uint32_t section_id);
    /*!
     * Undo the effect of start_rebuild.
     * Unmark the section mapping as in_rebuild and return to regular state with the currently update mapping.
     * \param section the section that has finished redeployment to a new device
     */
    void end_rebuild(uint32_t section_id);

    /*!
     *
     * Blocks untill all IOs to device are done (writes to section and read to device)
     * \param
     */
    void remove_section_from_device(uint32_t section_id, P::IO::BaseIO *dev);

    void remove_device_internal(P::IO::BaseIO *dev);


    /**********************
     * Additional functions
     **********************/

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

    inline P::IO::BaseIO *get_device_from_guid(P::GUID dev_guid) {
        Control::RemoteDevice *remote_device = _dev_agent->get_device(dev_guid);
        ASSERT_NOT_NULL(remote_device);
        P::IO::DevIO *dev_io = remote_device->get_devio();
        ASSERT_NOT_NULL(dev_io);
        return dev_io;
    }

    bool _is_activated = false;

    uint32_t _max_section_id;  // max active entry index in _section_mappings
    SectionMapping<MAX_DEVS_PER_SECTION> *_section_mappings;
    SectionMapping<MAX_DEVS> _section_zero_mapping;

    Control::DevAgent *_dev_agent;
};  // class MIOAgent

}  //  namespace MirroredIO
