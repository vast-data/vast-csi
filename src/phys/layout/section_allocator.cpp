#include "section_allocator.hpp"

#include "plasma/utils/macros.hpp"
#include "plasma/utils/assert.hpp"

namespace Layout {

/*!
 * Each section has a replication factor of 2 or 3. Third of the sections are triplicated (indices which are multiples of 3).
 * ---------------------------------------------------------------------------------------------------------------------------------
 * |section 1: duplicate|section 2: duplicate|section 3: triplicate|section 4: duplicate|section 5: duplicate|section 6: triplicate|
 * ---------------------------------------------------------------------------------------------------------------------------------
 * Each of the section types (duplicate|triplicate) has different address types. For example, the triplets contain the folowing:
 * ------------------------------------------------
 * | SHARD_MD | SYSTEM_STATE | WRITE_BUFFER | ... |
 * ------------------------------------------------
 *
 * Each address type has a block_size and block_count where each block is assigned to a shard:
 * block number X on sector 1 is mapped to shard X. block number X on sector 2 is mapped to shard X*2.
 */

constexpr AddrTypeConfig SectionAllocator::ADDR_TYPE_CONFIG[];

void SectionAllocator::init()
{
    LOOP(ReplicationFactor::COUNT, i) {
        SectionTypeConfig *conf = &_section_type_config[i];
        uint64_t offset = 0;
        LOOP(AddrType::COUNT, j) {
            conf->addr_type_offset[j] = offset;
            conf->addr_type_size[j] = ADDR_TYPE_CONFIG[j].block_count * ADDR_TYPE_CONFIG[j].block_size;
            offset += conf->addr_type_size[j];
        }
        ASSERT_OP(offset, <, SECTION_SIZE);
    }
}

void SectionAllocator::activate(uint32_t shard_count, uint32_t max_section_id)
{
    _shard_count = shard_count;
    _max_section_id = max_section_id;
}

P::IO::MirroredAddressToken SectionAllocator::translate(Address addr, size_t len)
{
    const AddrTypeConfig *addr_type_config = &ADDR_TYPE_CONFIG[(int)addr.addr_type];
    SectionTypeConfig *section_type_config = &_section_type_config[(int)addr_type_config->replication_factor];

    uint64_t block_offset = addr.offset % addr_type_config->block_size;
    ASSERT_OP(block_offset + len, <=, addr_type_config->block_size);
    uint64_t block_index = ((addr.offset / addr_type_config->block_size) + 1) * addr.shard_id;

    P::IO::MirroredAddressToken ret_addr;
    ret_addr.token_type = addr_type_config->token_type;
    ret_addr.section_id = get_absolute_section(addr_type_config->replication_factor, block_index / addr_type_config->block_count);
    ASSERT_OP(ret_addr.section_id, <, _max_section_id);

    // offset to start of address type
    ret_addr.byte_offset = section_type_config->addr_type_offset[(int)addr.addr_type];
    // + offset to blocks of previous shards
    ret_addr.byte_offset += block_index % addr_type_config->block_count * addr_type_config->block_size;
    // + offset into specific block
    ret_addr.byte_offset += block_offset;
    return ret_addr;
}

uint32_t SectionAllocator::get_absolute_section(ReplicationFactor replication_factor, uint32_t logical_section_id)
{
    uint32_t result;
    if (replication_factor == ReplicationFactor::DUPLICATE)
        result = logical_section_id + (logical_section_id / DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO);
    else
        result = logical_section_id * (DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO + 1);
    ASSERT_OP(result, <, _max_section_id);
    return result + 1; // skip section 0
}

uint32_t SectionAllocator::get_total_section_count(AddrType type)
{
    const AddrTypeConfig *addr_type_config = &ADDR_TYPE_CONFIG[(int)type];

    uint32_t numerator;
    uint32_t leftover;
    if (addr_type_config->replication_factor == ReplicationFactor::DUPLICATE) {
        numerator = DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO;
        leftover = _max_section_id % (DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO + 1);
    } else {
        numerator = 1;
        leftover = 0;
    }
    return _max_section_id * numerator / (DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO + 1) + leftover;
}

uint64_t SectionAllocator::get_total_addr_type_size(P::ShardId shard_id, AddrType type)
{
    const AddrTypeConfig *addr_type_config = &ADDR_TYPE_CONFIG[(int)type];
    uint32_t total_type_blocks = get_total_section_count(type) * addr_type_config->block_count;
    uint32_t shard_blocks = total_type_blocks / _shard_count + (shard_id < total_type_blocks % _shard_count);
    return shard_blocks * addr_type_config->block_size;
}

} // namespace Layout
