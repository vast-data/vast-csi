/* Copyright (C) Vast Data Ltd. */

/*!
 * \file section_allocator.hpp
 * \brief The section allocator maps addresses of different types of data (LAddress) to addresses on sections (that can be passed to MIO).
 *
 * The section allocator is used by several entities (EStore, System State, etc') that need to persist data on flash or memory.
 * Since multiple entities need to write data to the same sections, each section is hard-partiotioned between different types of data.
 * Each data type has the following configuration (SectionAllocator::ADDR_TYPE_CONFIG):
 * 1. How many times should it be replicated (2 or 3).
 * 2. Where should it be written: NVRAM or Memory.
 * 3. How many shards does it have.
 * 4. How is it layed out in a section: what is the block_size and block_count.
 *
 * Since each section has a replication factor, the data types are grouped by their replication factor to different section types.
 * Each section has a replication factor of 2 or 3. Currently, third of the sections are triplicated (indices which are multiples of 3):
 * ---------------------------------------------------------------------------------------------------------------------------------
 * |section 1: duplicate|section 2: duplicate|section 3: triplicate|section 4: duplicate|section 5: duplicate|section 6: triplicate|
 * ---------------------------------------------------------------------------------------------------------------------------------
 *
 * When mapping a LAddress to a section, several factors are taken into consideration:
 * 1. What logical block index it belongs to according to the address.shard_id and offset.
 * 2. What section offset it belongs to according to the block count and offset into the section.
 * 3. What section it belongs to according to the data type's replication factor and section index.
 */

#pragma once

#include "plasma/utils/units.hpp"
#include "plasma/utils/io.hpp"
#include "address.hpp"
#include "section_allocator.rpc.server.hpp"

namespace Layout {

enum class ShardType : uint8_t {
    NONE,
    ESTORE,
    COUNT
};

enum class ReplicationFactor : uint8_t {
    DUPLICATE,
    TRIPLICATE,
    COUNT
};

// This struct is used for configuring each AddrType
struct AddrTypeConfig {
    uint32_t block_size;
    uint32_t block_count;
    ShardType shard_type;
    ReplicationFactor replication_factor;
    P::IO::TokenType token_type;
};

// since replication is done on a section level, different replication factors split sections
// to different section types. The following struct is instantiated per ReplicationFactor
// and is derived from an array of AddrTypeConfigs.
struct SectionTypeConfig {
    uint64_t addr_type_offset[(int)AddrType::COUNT];
    uint32_t addr_type_size[(int)AddrType::COUNT];
};

class SectionAllocator : public SectionAllocatorServer {
public:
    void init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id);
    void do_activate(uint32_t estore_shard_count, uint32_t max_section_id);

    /*!
     * Translate a Address(addr_type,shard_id,offset) to a MIO Address(section,offset).
     * \param len used for asserting we don't exceed data type or sector boundaries.
     * \param addr address to translate.
     */
    P::IO::MirroredAddressToken translate(Address addr, size_t len);
    uint64_t get_total_addr_type_size(P::ShardId shard_id, AddrType type);
    uint32_t get_total_section_count(AddrType type);

    // RPC Calls
    void activate(SectionAllocatorActivateParams::RootReader *args, P::VProto::Empty::RootBuilder *res);

private:
    uint32_t _estore_shard_count;
    uint32_t _max_section_id;

    //TODO: adjust block_counts/block_size to fill sections
    static constexpr AddrTypeConfig ADDR_TYPE_CONFIG[(int)AddrType::COUNT] = {
        //block_size     block_count shard_type         replication_factor             token_type
        {0,              0,          ShardType::NONE,   ReplicationFactor::COUNT,      P::IO::TokenType::NVRAM}, // NONE
        {UNIT_MiB * 1,   1024,       ShardType::ESTORE, ReplicationFactor::DUPLICATE,  P::IO::TokenType::NVRAM}, // HANDLE_TABLE: 1GB
        {UNIT_KiB * 4,   1,          ShardType::ESTORE, ReplicationFactor::TRIPLICATE, P::IO::TokenType::NVRAM}, // SHARD_MD: 4KiB
        {UNIT_KiB * 4,   256,        ShardType::ESTORE, ReplicationFactor::DUPLICATE,  P::IO::TokenType::NVRAM}, // MD_BLOCKS: 1MiB
        {UNIT_MiB * 100, 600,        ShardType::ESTORE, ReplicationFactor::TRIPLICATE, P::IO::TokenType::NVRAM}, // WRITE_BUFFER: 60GiB
        {UNIT_KiB * 4,   256,        ShardType::ESTORE, ReplicationFactor::DUPLICATE,  P::IO::TokenType::NVRAM}, // TOKEN_MAPPER: 1MiB
        {UNIT_MiB * 4,   1,          ShardType::NONE,   ReplicationFactor::TRIPLICATE, P::IO::TokenType::NVRAM}, // SYSTEM_STATE: 4MiB
    };

    // third of the sections are triplicated, the rest are duplicated
    static const size_t DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO = 2;
    static const size_t SECTION_SIZE = 64 * UNIT_GiB;
    SectionTypeConfig _section_type_config[(int)ReplicationFactor::COUNT];

    uint32_t get_shard_count(const AddrTypeConfig *type_config);
    uint32_t get_absolute_section(ReplicationFactor replication_factor, uint32_t logical_section_id);
};

} // namespace Layout
