/* Copyright (C) Vast Data Ltd. */

/*!
 * \file shard_layout.hpp
 * \brief
 */
#pragma once

#include <estore/defs/estore_defs.hpp>
#include "plasma/utils/io.hpp"


namespace EStore {

// This implements a translation according to the XPoint layout.
// There is still no RDMA layout translation.
class ShardLayout {
public:
    void init();

    static size_t get_bs(EAddrType addr_type) { return EADDR_TYPE_BS[(int)addr_type]; };
    // len is for assert purposes. we don't allow access to a range that exceeds an allocation unit boundaries.
    P::IO::MirroredAddressToken translate(EAddress eaddr, size_t len);
    void get_addr_type_info(P::ShardId shard_id, EAddrType type, uint64_t *size_bytes);

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


