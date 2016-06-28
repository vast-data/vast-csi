#include "vmsg_pool.hpp"
#include <limits>
#include "modules/module_interface.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/execution/env.hpp"
#include "rdma_transport.hpp"

namespace P {
namespace VMsg {


static uint32_t calc_buffer_size(BufferType buffer_type)
{
    switch (buffer_type) {
        case BufferType::REPLY:
            /* fall throu */
        case BufferType::SERVER:
            return RPC_BUFFER_SIZE + sizeof(VMsgHeader) + sizeof(QueuedEvent);
        case BufferType::REQUEST:
            /* fall throu */
        case BufferType::RESPONSE:
            // request and response buffer also need room for the pending message struct
            return RPC_BUFFER_SIZE + sizeof(VMsgHeader) + sizeof(QueuedEvent) + sizeof(PendingMsg);
        default:
            PANIC();
    }
}

static uint32_t calc_n_buffers(BufferType buffer_type, ModuleResources *module_resources)
{
    ASSERT(module_resources->num_send_buffers <= std::numeric_limits<uint16_t>::max());
    ASSERT(module_resources->num_recv_buffers <= std::numeric_limits<uint16_t>::max());
    switch (buffer_type) {
        case BufferType::REPLY:
            return module_resources->num_send_buffers;
        case BufferType::SERVER:
            return module_resources->num_recv_buffers;
        case BufferType::REQUEST:
            return module_resources->num_send_buffers;
        case BufferType::RESPONSE:
            return module_resources->num_recv_buffers;
        default:
            PANIC();
    }
}

void VMsgPool::init(VMsgConfiguration *modules_resources)
{
    uint32_t num_silos = Env::get()->get_num_silos();
    LOOP(BUFFER_TYPE_COUNT, buffer_type) {
        LOOP(MODULES_COUNT, j) {
            _regions[buffer_type][j] = nullptr;
            CPool *pool = &_buffers[buffer_type][j];
            uint32_t buffer_size = calc_buffer_size((BufferType)buffer_type);
            uint32_t n_buffers = calc_n_buffers((BufferType)buffer_type, &modules_resources->modules[j]);
            // allocate at least 1 buffer in order to avoid pool initialization checks all over the place
            n_buffers = MAX(1, n_buffers);
            pool->init(num_silos, BUFFER_CACHE_SIZE, n_buffers, buffer_size);
        }
    }
}

void VMsgPool::destroy()
{
    LOOP(MODULES_COUNT, j) {
        LOOP(BUFFER_TYPE_COUNT, buffer_type) {
            // not doing leak checks since messaging buffers can be out of the pool during shutdown without this being a bug
            _buffers[buffer_type][j].destroy(false /*leak check*/);
        }
    }
}

void VMsgPool::register_buffers(RDMATransport *rdma_transport)
{
    LOOP(BUFFER_TYPE_COUNT, i) {
        LOOP(MODULES_COUNT, j) {
            CPool *pool = &_buffers[i][j];
            _regions[i][j] = rdma_transport->register_mem(pool->get_mem_ptr(), pool->get_mem_size());
            ASSERT(_regions[i][j] != nullptr);
        }
    }
}

void VMsgPool::unregister_buffers(RDMATransport *rdma_transport)
{
    LOOP(BUFFER_TYPE_COUNT, i) {
        LOOP(MODULES_COUNT, j) {
            rdma_transport->unregister_mem(_regions[i][j]);
        }
    }
}

}
}
