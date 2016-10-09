#include "plasma/utils/assert.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/trace/emitter.hpp"
#include "name_range_block.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

namespace EStore {

void NameRangeBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::NAME_RANGE_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    add_used_bytes(sizeof(uint16_t));
    ZERO_LAST(NameRange);
}

NameRange *NameRangeBlock::find_range(const char *name)
{
    NameRange *res = (NameRange *)payload_start();
    TRAVERSE_CONTENT(NameRange, range) {
        int cmp_res = strncmp(name, range->name, range->len);
        if (cmp_res >= 0) {
            res = range;
        } else {
            return res;
        }
    }
    return res;
}

EStoreRes NameRangeBlock::add_range(const char *name, LAddress addr)
{
    size_t name_len = strnlen(name, get_size());
    if (name_len + sizeof(NameRange) + sizeof(uint16_t) > space_left()) {
        return EStoreRes::NO_MEM;
    }
    // TODO handle range overwrite
    NameRange *range = (NameRange *)payload_start();
    if (range->len > 0) {
        range = find_range(name);
        // the new range should be added following this one
        char *src = (char *)range + range->len + sizeof(NameRange);
        char *dst = src + name_len + sizeof(NameRange);
        // move the ranges following the range we found in order to make space for the new range
        memmove(dst, src, get_used_bytes() - ((P::byte *)range - header_offset()));
        range = (NameRange*)src;
    }

    // TODO deal with used bytes in case of composite block
    // now fill in the new range
    range->len = name_len;
    range->bitmap_addr = addr;
    memcpy(range->name, name, name_len);
    add_used_bytes(sizeof(NameRange) + name_len);
    ZERO_LAST(NameRange);

    return EStoreRes::OK;
}

LAddress NameRangeBlock::get_address(const char *name)
{
    if (!has_ranges()) {
        return Layout::EMPTY_ADDRESS;
    }
    return find_range(name)->bitmap_addr;
}

bool NameRangeBlock::has_ranges()
{
    NameRange *range = (NameRange *)payload_start();
    return range->len > 0;
}

void NameRangeBlock::trace()
{
    int i = 0;
    TRAVERSE_CONTENT(NameRange, range) {
        PTC_DEBUG("range(%d) name=%s bitmap_addr=%lx", i, range->name, *(uint64_t*)&range->bitmap_addr);
        ++i;
    }
}

}
