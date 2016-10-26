#include "plasma/execution/silo.hpp"
#include "phys/layout/block_allocator.hpp"
#include "phys/mirrored_io/mio.hpp"

#define CURRENT_COMPONENT ComponentId::ESTORE

using EStore::IO_ALIGNMENT;
using EStore::NVRAM_MD_BLOCK_SIZE;
using EStore::EStoreRes;
using Layout::MirroredAddress;
using Layout::AddrType;
using MirroredIO::MIO;

namespace Layout {

void BlockAllocator::init(MirroredIO::MIO *mio, Layout::SectionAllocator *section_allocator) {
    _mio = mio;
    _section_allocator = section_allocator;

    _head_mio_buf.init((P::byte *)aligned_alloc(IO_ALIGNMENT, NVRAM_ATOMIC_BLOCK_SIZE), NVRAM_ATOMIC_BLOCK_SIZE);
    _next_mio_buf.init((P::byte *)aligned_alloc(IO_ALIGNMENT, NVRAM_ATOMIC_BLOCK_SIZE), NVRAM_ATOMIC_BLOCK_SIZE);
    _head_data = (BlocksList *)_head_mio_buf.get_data();
    _next_data = (BlocksList *)_next_mio_buf.get_data();
    DEBUG_ASSERT(sizeof(BlocksList) <= _head_mio_buf.get_data_size());
}

bool BlockAllocator::create(P::ShardId shard_id, LAddrType type) {
    Layout::MirroredAddress head_addr = _section_allocator->translate_block(shard_id, type, 0);
    _head_data->count = 0;
    _head_data->total_count = 0;
    _head_data->next = 0;

    bool write_ret = _mio->protected_write(head_addr, &_head_mio_buf, nullptr, nullptr);
    if (write_ret == false) {
        PT_ERROR(DATA, "failed creating block list (IOError)");
        return false;
    }
    return true;
}

EStoreRes BlockAllocator::alloc_from_extra_space(P::ShardId shard_id, LAddrType type, BlockAddr *next_block OUT) {
    uint32_t new_blocks = _section_allocator->get_total_addr_type_size(shard_id, type) /
                          _section_allocator->get_addr_type_block_size(type);
    if (new_blocks <= _head_data->total_count + 1 /*HEAD*/) {
        PT_ERROR(DATA, "block allocator out of space");
        return EStoreRes::NO_MEM;
    }

    new_blocks -= _head_data->total_count + 1 /*HEAD*/;
    new_blocks = P_MIN((int32_t)BLOCKS_PER_PAGE / 2, new_blocks);
    _head_data->count = new_blocks - 1;
    LOOP(_head_data->count, i) {
        _head_data->buffers[i] = (_head_data->total_count + 1 /*HEAD*/) + i;
    }
    _head_data->total_count += new_blocks;
    *next_block = _head_data->total_count;
    return EStoreRes::OK;
}

EStoreRes BlockAllocator::alloc(P::ShardId shard_id, LAddrType type, LAddress *eaddr OUT) {
    //currently unused: MirroredIO::WorkerID worker_id = P::Silo::get_current_silo_id();
    //_lock_addr.byte_offset=_section_allocator->shard_id_to_offset(eaddr->addr_type, eaddr->shard_id);
    Layout::MirroredAddress head_addr = _section_allocator->translate_block(shard_id, type, 0);
    MirroredIO::MIO::Buffer *mio_buf = &_head_mio_buf;
    BlockAddr next_block;

    bool write_ret;

    //_mio->lock(_lock_addr, worker_id);
    MIO::ReadRet ret = _mio->protected_read(head_addr, &_head_mio_buf, true, nullptr);
    if (ret != MIO::ReadRet::SUCCESS) {
        PT_ERROR(DATA, "failed reading block list 'head' (IOError)");
        return EStoreRes::IO_ERROR;
    }
    if (_head_data->count == 0)
    {
        if (_head_data->next) {
            next_block = _head_data->next;
            MirroredAddress mirrored_next = _section_allocator->translate_block(shard_id, type, _head_data->next);
            ret = _mio->protected_read(mirrored_next, &_next_mio_buf, false, nullptr);
            if (ret != MIO::ReadRet::SUCCESS) {
                PT_ERROR(DATA, "failed reading block list 'next' (IOError)");
                return EStoreRes::IO_ERROR;
            }
            DEBUG_ASSERT(_next_data->count);
            DEBUG_ASSERT(_next_data->total_count == 0);
            DEBUG_ASSERT(_head_data->total_count);
            mio_buf = &_next_mio_buf;
            _next_data->total_count = _head_data->total_count;
        }
        else {
            EStoreRes eres = alloc_from_extra_space(shard_id, type, &next_block);
            if (eres != EStoreRes::OK) {
                return eres;
            }
        }
    }
    else {
        next_block = _head_data->buffers[--_head_data->count];
    }

    *eaddr = { .shard_id=shard_id, .addr_type=type, .offset=next_block*_section_allocator->get_addr_type_block_size(type) };
    write_ret = _mio->protected_write(head_addr, mio_buf, nullptr, nullptr);
    if (write_ret == false) {
        PT_ERROR(DATA, "failed writting block list 'head' (IOError)");
        return EStoreRes::IO_ERROR;
    }
    //_mio->unlock(_lock_addr, worker_id);
    return EStoreRes::OK;
}

bool BlockAllocator::free(const LAddress *eaddr) {
    //currently unused: MirroredIO::WorkerID worker_id = P::Silo::get_current_silo_id();
    //_lock_addr.byte_offset=_section_allocator->shard_id_to_offset(eaddr->addr_type, eaddr->shard_id);
    Layout::MirroredAddress head_addr = _section_allocator->translate_block(eaddr->shard_id, eaddr->addr_type, 0);
    BlockAddr new_block = eaddr->offset / _section_allocator->get_addr_type_block_size(eaddr->addr_type);
    DEBUG_ASSERT(eaddr->offset % _section_allocator->get_addr_type_block_size(eaddr->addr_type) == 0);
    DEBUG_ASSERT(eaddr->addr_type == LAddrType::MD_BLOCKS)
    DEBUG_ASSERT(new_block);
    bool write_ret;

    //_mio->lock(_lock_addr, worker_id);
    MIO::ReadRet read_ret = _mio->protected_read(head_addr, &_head_mio_buf, true, nullptr);
    if (read_ret != MIO::ReadRet::SUCCESS) {
        PT_ERROR(DATA, "failed reading block list 'head' (IOError)");
        return false;
    }
    if (_head_data->count == BLOCKS_PER_PAGE)
    {
        _next_data->count = BLOCKS_PER_PAGE - BLOCKS_PER_PAGE/2;
        _next_data->next = _head_data->next;
        _head_data->count = BLOCKS_PER_PAGE/2;
        _head_data->total_count = 0;
        _head_data->next = new_block;
        memcpy(_next_data->buffers,
               &_head_data->buffers[BLOCKS_PER_PAGE/2],
               (BLOCKS_PER_PAGE - BLOCKS_PER_PAGE/2)*sizeof(BlockAddr));

        MirroredAddress mirrored_addr = _section_allocator->translate(*eaddr, 1);
        write_ret = _mio->protected_write(mirrored_addr, &_next_mio_buf, nullptr, nullptr);
        if (write_ret == false) {
            PT_ERROR(DATA, "failed writting block list 'next' (IOError)");
            return false;
        }
    }
    else {
        _head_data->buffers[_head_data->count++] = new_block;
    }

    write_ret = _mio->protected_write(head_addr, &_head_mio_buf, nullptr, nullptr);
    if (write_ret == false) {
        PT_ERROR(DATA, "failed writting block list 'head' (IOError)");
        return false;
    }
    //_mio->unlock(_lock_addr, worker_id);
    return true;
}

}
