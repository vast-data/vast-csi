/* Copyright (C) Vast Data Ltd. */

/*!
 * \file section_allocator.hpp
 * \brief
 */
#pragma once

#include "plasma/utils/types.hpp"

namespace Layout {

enum class AddrType : uint64_t {
    NONE,
    // Element Store block types
    HANDLE_TABLE,
    SHARD_MD,
    MD_BLOCKS,
    WRITE_BUFFER,
    CONTAINED,

    // Control
    SYSTEM_STATE,

    // Remote mem via rdma
    MEM,
    // Direct Flash resilient address
    FLASH,
    // Direct NVRAM resilient address
    NVRAM,

    COUNT
};
static_assert((uint64_t)AddrType::COUNT < 16, "AddrType cannot take more than 4 bits");

enum AddressFieldBitSize {
    // General
    TYPE = 4,

    // Xpoint
    MIRRORED_SECTION = 20,      // max section count:       1M
    MIRRORED_BYTE_OFFSET = 40,  // max section size:        1TB

    // Flash
    FLASH_BIG_BLOCK = 30,       // max big blocks count:    1G
    FLASH_BYTE_OFFSET = 30,     // max big block size:      1GB

    // Layout (MVRAM Logical address)
    SHARD_ID = 16,
    LAYOUT_BYTE_OFFSET = 44,
};

#define ADDRESS_STRUCT_PREFIX AddrType addr_type : AddressFieldBitSize::TYPE;

struct LAddress {
    ADDRESS_STRUCT_PREFIX
    uint64_t shard_id  : AddressFieldBitSize::SHARD_ID;
    uint64_t offset    : AddressFieldBitSize::LAYOUT_BYTE_OFFSET; //TODO: currently in bytes, other resolutions can be supported.

    uint64_t as_number() const { return *(uint64_t *)this; }
};

static const LAddress EMPTY_ADDRESS = {AddrType::NONE, 0, 0};
static const LAddress CONTAINED_ADDRESS = {AddrType::CONTAINED, 0, 0};

// used for both Mem and XPointDirect
struct MirroredAddress {
    ADDRESS_STRUCT_PREFIX
    uint64_t section_id  :   AddressFieldBitSize::MIRRORED_SECTION;
    uint64_t byte_offset :   AddressFieldBitSize::MIRRORED_BYTE_OFFSET;

    uint64_t as_number() const
    { return *(uint64_t *)this; }

    static const uint64_t ATOMIC_BLOCK_SIZE = 4<<10;

    bool supports_atomic_ops() const
    {
        return (addr_type == AddrType::MEM);
    }

    bool equals(const MirroredAddress *obj) const
    {
        return as_number() == obj->as_number();
    }

    static const uint64_t STATIC_SECTION_ID = 0;
};

struct FlashAddress {
    ADDRESS_STRUCT_PREFIX
    uint64_t big_block_id:  AddressFieldBitSize::FLASH_BIG_BLOCK;
    uint64_t byte_offset:   AddressFieldBitSize::FLASH_BYTE_OFFSET;
};

struct MapperAddress {
    ADDRESS_STRUCT_PREFIX
    uint64_t bla:60;
    uint64_t la;
};

struct DataReductionAddress {
    ADDRESS_STRUCT_PREFIX
    uint64_t blala:60;
    uint64_t li;
};

class AddressToken {
public:

    union {
        ADDRESS_STRUCT_PREFIX
        MirroredAddress m_address;
        FlashAddress f_address;
        LAddress l_address;
    };


    bool is_mirrored_address() const
    {
        return (addr_type == AddrType::MEM) || (addr_type == AddrType::NVRAM);
    }

};

struct TokenVec {
    AddressToken token;
    uint32_t len;
};

struct TokenVecs {
    uint32_t count;
    TokenVec *vecs;
};
}

typedef Layout::AddrType LAddrType;
typedef Layout::LAddress LAddress;
