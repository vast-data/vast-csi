/* Copyright (C) Vast Data Ltd. */

/*!
 * \file section_allocator.hpp
 * \brief
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

    // len is for assert purposes. we don't allow access to a range that exceeds slice boundaries.
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
