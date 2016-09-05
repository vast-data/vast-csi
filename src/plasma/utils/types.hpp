/* Copyright (C) Vast Data Ltd. */

/*!
 * \file types.hpp
 * \brief Types used throughout plasma
 */
#pragma once

#include <cstdint>
#include <cstddef>
#include <uuid/uuid.h>
#include <stdio.h>
#include <iomanip>

namespace P {

typedef uint8_t byte;
typedef int32_t Index;
const Index INVALID_INDEX = -1;
using std::size_t;

class GUID {
public:
    void init()
    {
        uuid_generate(_value);
    }

    bool equals(GUID *other) const { return uuid_compare(_value, other->_value) == 0; }

    uint64_t get_first_half()
    {
        return *((uint64_t*) _value);
    }

    uint64_t get_second_half()
    {
        return *(((uint64_t*) _value) + 1);
    }

private:
    uuid_t _value;
} __attribute__ ((packed, aligned(8)));
static_assert(sizeof(GUID) == 16, "sizeof(GUID) should be 16 bytes");

}

template<class C, class T>
std::basic_ostream<C, T>& operator<<(std::basic_ostream<C, T>& os, P::GUID guid)
{
    return os << std::hex << guid.get_first_half() << guid.get_second_half();
}
