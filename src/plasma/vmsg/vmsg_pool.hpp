/* Copyright (C) Vast Data Ltd. */
/*!
*  file vmsg_pool.hpp
* \brief The container for VMsg buffers
*/

#pragma once

#include "plasma/memory/cpool.hpp"
#include "vmsg_defs.hpp"

namespace P {
namespace VMsg {

class RDMATransport;

typedef struct MemRegion MemRegion;

class VMsgPool {
public:
    void init(VMsgConfiguration *modules_resources);

    void destroy();

    void register_buffers(RDMATransport *rdma_transport);

    void unregister_buffers(RDMATransport *rdma_transport);

    void *alloc(BufferType buffer_type, ModuleId module_id, Index cache_index)
    {
        return _buffers[(int)buffer_type][(int)module_id].alloc(cache_index);
    }

    void free_address(BufferType buffer_type, ModuleId module_id, Index cache_index, void *buffer)
    {
        return _buffers[(int)buffer_type][(int)module_id].free_address(cache_index, buffer);
    }

    void free(BufferType buffer_type, ModuleId module_id, Index cache_index, Index buffer_index)
    {
        return _buffers[(int)buffer_type][(int)module_id].free(cache_index, buffer_index);
    }

    MemRegion *get_region(BufferType buffer_type, ModuleId module_id)
    {
        return _regions[(int)buffer_type][(int)module_id];
    }

    void *msg_id_to_address(MsgId id)
    {
        return index_to_address((BufferType)id.buffer_type, (ModuleId)id.module_id, id.buffer_index);
    }

    void *index_to_address(BufferType buffer_type, ModuleId module_id, Index index)
    {
        return _buffers[(int)buffer_type][(int)module_id].index_to_address(index);
    }

    Index address_to_index(BufferType buffer_type, ModuleId module_id, void *buffer)
    {
        return _buffers[(int)buffer_type][(int)module_id].address_to_index(buffer);
    }

    // message buffers layout, only the header + payload + piggyback is sent over the network.
    // the payload and piggyback data share the same space, piggyback data is send only if there
    // is some space avalaible
    // -------------------------------------------------------------------------------------
    // | header | payload | piggyback data (optional) | QueuedEvent | PendingMsg (optional) |
    // -------------------------------------------------------------------------------------

    static void *msg_header_to_payload(VMsgHeader *header)
    {
        return (byte *)header + sizeof(VMsgHeader);
    }

    static PiggybackData *msg_header_to_piggyback(VMsgHeader *header)
    {
        return (PiggybackData *)((byte *)header + sizeof(VMsgHeader) + header->payload_size);
    }

    static QueuedEvent *msg_header_to_queued_event(VMsgHeader *header)
    {
        return (QueuedEvent *)((byte *)header + sizeof(VMsgHeader) + RPC_BUFFER_SIZE);
    }

    static PendingMsg *msg_header_to_pending_msg(VMsgHeader *header)
    {
        return (PendingMsg *)((byte *)header + sizeof(VMsgHeader) + sizeof(QueuedEvent) + RPC_BUFFER_SIZE);
    }

    static VMsgHeader *msg_payload_to_header(void *payload)
    {
        return (VMsgHeader *)((byte *)payload - sizeof(VMsgHeader));
    }


private:
    static const uint32_t BUFFER_CACHE_SIZE = 64;
    // per module buffer pools (see Buffers Life Cycle section in the design doc)
    P::CPool _buffers[BUFFER_TYPE_COUNT][MODULES_COUNT];
    MemRegion *_regions[BUFFER_TYPE_COUNT][MODULES_COUNT];
};

}
}