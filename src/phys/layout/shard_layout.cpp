#include "../layout/shard_layout.hpp"

#include "plasma/utils/macros.hpp"
#include "plasma/utils/assert.hpp"

/* initial layout implementation:
 *
 *\\
 * \\
 *  \\ Sections: 1      2       3       4       5
 *   \\
 *    \\
 *     \\   =========================================
 *          | AUnit | AUnit | AUnit | AUnit | AUnit |
 * Shards: 1|  1:1  |       |       |       |       |
 *          |-------|-------|-------|-------|-------|
 *          |       |       |       |       |       |
 *         2|       |       |       |       |       |
 *          |-------|-------|-------|-------|-------|
 *          |       |       |       |       |       |
 *         3|       |       |       |       |       |
 *          |-------|-------|-------|-------|-------|
 *          |       |       |       |       |       |
 *         4|       |       |       |       |       |
 *          =========================================
 */

namespace Phys {

namespace Layout {

void ShardLayout::init()
{
    _allocation_unit_size = 0;
    LOOP(EAddrType::COUNT, i) {
        _EAddrType_base_offset[i] = _allocation_unit_size;
        _EAddrType_size_in_unit[i] = EADDR_TYPE_BLOCK_COUNT[i] * EADDR_TYPE_BS[i];
        _allocation_unit_size += _EAddrType_size_in_unit[i];
    }

    ASSERT_OP(_allocation_unit_size * SHARD_COUNT, <=, MINIMAL_NVRAM_SIZE / SECTIONS_IN_DBOX);
}

P::IO::MirroredAddressToken ShardLayout::translate(EAddress eaddr, size_t len)
{
    uint64_t offset_in_curr_unit = eaddr.offset % _EAddrType_size_in_unit[(int)eaddr.addr_type];
    ASSERT_OP(len, <=, _EAddrType_size_in_unit[(int)eaddr.addr_type] - offset_in_curr_unit);

    P::IO::MirroredAddressToken ret_addr;
    ret_addr.token_type = P::IO::TokenType::NVRAM;
    ret_addr.section_id = eaddr.offset / _EAddrType_size_in_unit[(int)eaddr.addr_type];
    ASSERT_OP(ret_addr.section_id, <, SECTIONS_IN_DBOX * DBOX_COUNT);

    ret_addr.byte_offset = _EAddrType_base_offset[(int)eaddr.addr_type] + offset_in_curr_unit;

    return ret_addr;
}

}
}
