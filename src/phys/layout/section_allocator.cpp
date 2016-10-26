#include "section_allocator.hpp"

#include "plasma/utils/macros.hpp"
#include "plasma/utils/assert.hpp"
#include "globals.hpp"

namespace Layout {

constexpr AddrTypeConfig SectionAllocator::ADDR_TYPE_CONFIG[];

void SectionAllocator::init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id)
{
    _active = false;
    register_server(silo_id, module_id, rpc_fiber_group_id);
}

void SectionAllocator::do_activate(uint32_t estore_shard_count, uint32_t max_section_id)
{
    if (estore_shard_count < MAXIMUM_SHARDS_PER_SECTION)
        ASSERT(global_test_mode);
    _estore_shard_count = estore_shard_count;
    _max_section_id = max_section_id;
    _active = true;

    LOOP(ReplicationFactor::COUNT, i) {
        SectionTypeConfig *conf = &_section_type_config[i];
        uint64_t offset = 0;
        LOOP(AddrType::COUNT, j) {
            conf->addr_type_offset[j] = offset;
            conf->addr_type_blocks[j] = ADDR_TYPE_CONFIG[j].shard_block_count * P_MIN(MAXIMUM_SHARDS_PER_SECTION, get_shard_count(&ADDR_TYPE_CONFIG[j]));
            conf->addr_type_size[j] = conf->addr_type_blocks[j] * ADDR_TYPE_CONFIG[j].block_size;
            offset += conf->addr_type_size[j];
        }
        ASSERT_OP(offset, <, SECTION_SIZE);
    }
}

void SectionAllocator::activate(SectionAllocatorActivateParams::RootReader *args, UNUSED P::VProto::Empty::RootBuilder *res)
{
    do_activate(args->get_estore_shard_count(), args->get_max_section_id());
}

uint32_t SectionAllocator::get_shard_count(const AddrTypeConfig *type_config)
{
    ASSERT(_active);
    return type_config->shard_type == ShardType::ESTORE ? _estore_shard_count : 1;
}

Layout::MirroredAddress SectionAllocator::translate(LAddress addr, size_t len)
{
    const AddrTypeConfig *addr_type_config = &ADDR_TYPE_CONFIG[(int)addr.addr_type];
    SectionTypeConfig *section_type_config = &_section_type_config[(int)addr_type_config->replication_factor];
    DEBUG_ASSERT_OP(addr.shard_id, <, get_shard_count(addr_type_config));
    DEBUG_ASSERT_OP(addr.offset, <, get_total_addr_type_size(addr.shard_id, addr.addr_type));

    uint64_t block_offset = addr.offset % addr_type_config->block_size;
    ASSERT_OP(block_offset + len, <=, addr_type_config->block_size);
    uint64_t block_index = addr.offset / addr_type_config->block_size * get_shard_count(addr_type_config) + addr.shard_id;

    Layout::MirroredAddress ret_addr;
    ret_addr.addr_type = addr_type_config->token_type;
    ret_addr.section_id = get_absolute_section(addr_type_config->replication_factor, block_index / section_type_config->addr_type_blocks[(int)addr.addr_type]);

    // offset to start of address type
    ret_addr.byte_offset = section_type_config->addr_type_offset[(int)addr.addr_type];
    // + offset to blocks of previous shards
    ret_addr.byte_offset += block_index % section_type_config->addr_type_blocks[(int)addr.addr_type] * addr_type_config->block_size;
    // + offset into specific block
    ret_addr.byte_offset += block_offset;
    return ret_addr;
}

/* static */ ReplicationFactor SectionAllocator::get_section_replication_factor(uint32_t section_id)
{
    ASSERT_OP(section_id, !=, 0);
    return section_id % (DUPLICATION_TO_TRIPLICATION_SECTION_COUNT_RATIO + 1) == 0
        ? ReplicationFactor::TRIPLICATE
        : ReplicationFactor::DUPLICATE;
}

Layout::MirroredAddress SectionAllocator::translate_block(P::ShardId shard_id, LAddrType type, P::Index index)
{
    LAddress addr = {.shard_id=shard_id, .addr_type=type, .offset=ADDR_TYPE_CONFIG[(int)type].block_size * index};
    return translate(addr, ADDR_TYPE_CONFIG[(int)type].block_size);
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

uint64_t SectionAllocator::get_total_addr_type_size(UNUSED P::ShardId shard_id, AddrType type)
{
    const AddrTypeConfig *addr_type_config = &ADDR_TYPE_CONFIG[(int)type];
    SectionTypeConfig *section_type_config = &_section_type_config[(int)addr_type_config->replication_factor];
    uint32_t total_blocks = get_total_section_count(type) * section_type_config->addr_type_blocks[(int)type];
    return total_blocks / get_shard_count(addr_type_config) * addr_type_config->block_size;
}

uint32_t SectionAllocator::get_addr_type_block_size(AddrType type) {
    return ADDR_TYPE_CONFIG[(int)type].block_size;
}

uint32_t SectionAllocator::get_addr_type_shard_count(AddrType type) {
    const AddrTypeConfig *addr_type_config = &ADDR_TYPE_CONFIG[(int)type];
    return get_shard_count(addr_type_config);
}

} // namespace Layout
