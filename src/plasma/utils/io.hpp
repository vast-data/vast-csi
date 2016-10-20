/* Copyright (C) Vast Data Ltd. */
/*!
 * \file io.hpp
 * \brief IO related definitions
 */

#pragma once

#include <sys/uio.h>
#include "types.hpp"

namespace P {

namespace IO {

typedef struct iovec IOVec;
class IOVecs {
public:
    uint32_t count;
    IOVec *iovecs;

    size_t total_length() const
    {
        size_t ret = 0;
        for (uint32_t i = 0; i < count; ++i) {
            ret += iovecs[i].iov_len;
        }
        return ret;
    }

    void trace();
};

typedef uint64_t Baddr;

enum class TokenType : uint64_t
{
    MEM,              // Remote mem via rdma
    NVRAM,            // Direct NVRAM resilient address
    FLASH,            // Direct Flash resilient address
    MD_MAPPED,        // MD block mapper indirection
    DR_MAPPED,        // Data reduction indirection
    TOKEN_TYPE_COUNT
};

enum TokenFieldBitSize
{
    // General
    TYPE = 4,

    // Xpoint
    MIRRORED_SECTION = 20,      // max section count:       1M
    MIRRORED_BYTE_OFFSET = 40,  // max section size:        1TB

    // Flash
    FLASH_BIG_BLOCK = 30,       // max big blocks count:    1G
    FLASH_BYTE_OFFSET = 30,     // max big block size:      1GB
};


#define TOKEN_MAX_SIZE  (16)
#define TOKEN_STRUCT_PERFIX TokenType token_type : TokenFieldBitSize::TYPE;

static_assert((int)TokenType::TOKEN_TYPE_COUNT <= 1 << (int)TokenFieldBitSize::TYPE, "Too many token types!");

// used for both Mem and XPointDirect
class MirroredAddressToken
{
public:
    TOKEN_STRUCT_PERFIX
    uint64_t section_id  :   TokenFieldBitSize::MIRRORED_SECTION;
    uint64_t byte_offset :   TokenFieldBitSize::MIRRORED_BYTE_OFFSET;

    bool supports_atomic_ops() const
    {
        return (token_type == TokenType::MEM);
    }

    bool equals(const MirroredAddressToken *obj) const {
        return token_type == obj->token_type && section_id == obj->section_id && byte_offset == obj->byte_offset; 
    }

    static const uint64_t STATIC_SECTION_ID = 0;
};

struct FlashAddressToken
{
    TOKEN_STRUCT_PERFIX
    uint64_t big_block_id:  TokenFieldBitSize::FLASH_BIG_BLOCK;
    uint64_t byte_offset:   TokenFieldBitSize::FLASH_BYTE_OFFSET;
};

struct MapperAddressToken
{
    TOKEN_STRUCT_PERFIX
    uint64_t bla:60;
    uint64_t la;
};

struct DataReductionAddressToken
{
    TOKEN_STRUCT_PERFIX
    uint64_t blala:60;
    uint64_t li;
};

class AddressToken
{
public:

    union {
        TOKEN_STRUCT_PERFIX
        MirroredAddressToken mirrored_token;
        FlashAddressToken f_token;
        MapperAddressToken mapper_token;
        DataReductionAddressToken dr_token;
    };


    bool is_mirrored_address() const
    {
        return (token_type == TokenType::MEM) ||
               (token_type == TokenType::NVRAM);
    }

    uint64_t atomic_block_size() const
    {
        return atomic_block_size_of_type(token_type);
    }

    static uint64_t atomic_block_size_of_type(TokenType type)
    {
        return atomic_block_sizes[(int)type];
    }


//    operator +? +=?
//    void add(size_t bytes)
//    {
//        DEBUG_ASSERT(is_byte_addressable());
//        token += bytes;
//    };

    // Todo: Set real attributes here
    static constexpr uint64_t atomic_block_sizes[(int)TokenType::TOKEN_TYPE_COUNT] = { 1<<10, 4<<10, 4<<10, 4<<10, UINT64_MAX };




//    bool is_byte_addressable()
//    {
//        return (token.base.tokenType == TokenType::XPointDirect);
//    }
};

static_assert(sizeof(AddressToken) <= TOKEN_MAX_SIZE, "Some token structure is too big!");

}
}
