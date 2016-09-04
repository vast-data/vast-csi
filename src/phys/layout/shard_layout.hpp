/* Copyright (C) Vast Data Ltd. */

/*!
 * \file shard_layout.hpp
 * \brief
 */
#pragma once

#include "plasma/utils/io.hpp"

////////////////////////////////////////////////////////////////////////////////////
// TODO: copy from Asaf Estore code: remove this!

enum class EAddrType : uint64_t {
    NONE                = 0,
    HANDLE_TABLE        = 1,
    SHARD_MD            = 2, // a single block
    MD_BLOCKS           = 3,
    WRITE_BUFFER        = 4,
    TOKEN_MAPPER        = 5, // ?
    CONTAINED           = 6,
    FLASH               = 7,

    COUNT
};
static_assert((uint64_t)EAddrType::COUNT < 16, "EAddrType cannot take more than 4 bits");

typedef uint64_t VirtualBucketId;

// TODO might need to support flash addr here
struct EAddress {
    EAddrType addr_type:4;
    uint64_t shard_id:16;
    uint64_t offset:44; // SHOULD DETERMINE IF THIS IS IN BS OR BYTES

    uint64_t as_number() { return *(uint64_t *)this; }
};


/////////////////////////////////////////////////////////////////////////////////////////////////////////////

namespace Phys {
namespace Layout {

// This implements a translation according to the XPoint layout.
// There is still no RDMA layout translation.
class ShardLayout {
public:
    void init();

    static size_t get_bs(EAddrType addr_type) { return EADDR_TYPE_BS[(int)addr_type]; };
    // len is for assert purposes. we don't allow access to a range that exceeds an allocation unit boundaries.
    P::IO::MirroredAddressToken translate(EAddress eaddr, size_t len);

protected:

    static constexpr size_t EADDR_TYPE_BS[(int)EAddrType::COUNT] = { 0, 4<<10, 4<<10, 4<<10, 100UL<<20, 4<<10, 4<<10, 4<<10 };
    static constexpr size_t EADDR_TYPE_BLOCK_COUNT[(int)EAddrType::COUNT] = { 0, 10, 1, 100, 5, 10, };
    static const size_t SHARD_COUNT = 1<<10;
    static const size_t MINIMAL_NVRAM_SIZE = 1UL<<40;
    static const size_t SECTIONS_IN_DBOX = 1<<4;
    static const size_t SECTION_SIZE = MINIMAL_NVRAM_SIZE / SECTIONS_IN_DBOX;

    // TODO: this should be a mutable value
    static const size_t DBOX_COUNT = 2;

    uint64_t _EAddrType_base_offset[(int)EAddrType::COUNT];
    uint64_t _EAddrType_size_in_unit[(int)EAddrType::COUNT];
    uint64_t _allocation_unit_size;
};

}
}


