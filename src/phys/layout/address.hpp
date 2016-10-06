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
    HANDLE_TABLE,
    SHARD_MD,
    MD_BLOCKS,
    WRITE_BUFFER,
    TOKEN_MAPPER,
    CONTAINED,
    FLASH,
    SYSTEM_STATE,

    COUNT
};
static_assert((uint64_t)AddrType::COUNT < 16, "AddrType cannot take more than 4 bits");

struct Address {
    AddrType addr_type : 4;
    uint64_t shard_id  : 16;
    uint64_t offset    : 44; //TODO: currently in bytes, other resolutions can be supported.

    uint64_t as_number() { return *(uint64_t *)this; }
};
static const Address EMPTY_ADDRESS     = { AddrType::NONE, 0, 0 };
static const Address CONTAINED_ADDRESS = { AddrType::CONTAINED, 0, 0 };

}

typedef Layout::AddrType LAddrType;
typedef Layout::Address LAddress;
