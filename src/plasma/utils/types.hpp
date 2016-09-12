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
    static const size_t STRING_LENGTH = 37; // includes null termination

    void init()
    {
        uuid_generate(_value);
    }

    bool init_from_string(const char *string)
    {
        // returns -1 on failure and 0 on success
        return uuid_parse(string, _value) == 0;
    }

    static const size_t STRING_SIZE = 37;

    /*!
     * Prints 37 characters to given buffer.
     * Example output: "1b4e28ba-2fa1-11d2-883f-0016d3cca427" + "\0"
     */
    void to_string(char *string)
    {
        uuid_unparse(_value, string);
    }

    static GUID create()
    {
        GUID guid;
        guid.init();
        return guid;
    }

    bool equals(GUID other) const { return uuid_compare(_value, other._value) == 0; }

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
    char string[P::GUID::STRING_SIZE];
    guid.to_string(string);
    return os << string;
}
