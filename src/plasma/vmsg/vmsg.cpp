#include "vmsg.hpp"
#include "globals.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/fiber/provider.hpp"
#include "plasma/internal.hpp"
#include "plasma/trace/emitter.hpp"

namespace P {
namespace VMsg {

void VMsg::init(VMsgConfiguration *vmsg_configuration)
{
    _vmsg_configuration = *vmsg_configuration;
    PT_INFO(DATA, "initializing VMsg local_env_id=%hu n_silos=%u", vmsg_configuration->local_env_id,
            vmsg_configuration->n_silos);
    _started = false;
    LOOP(ModuleId::COUNT, i) {
        LOOP(ModuleId::COUNT, j) {
            _module_pairs[i][j] = TransportType::NONE;
        }
    }

    _poll_lock.init();
    _vmsg_pool.init(&_vmsg_configuration);
    _address_table.init();
    _rdma_transport.init(vmsg_configuration, &_address_table);

    uint32_t n_acks = 0;
    LOOP(ModuleId::COUNT, i) {
        n_acks += _vmsg_configuration.modules[i].num_send_buffers;
    }

    _silos_context = new SiloContext[_vmsg_configuration.n_silos];
    LOOP(vmsg_configuration->n_silos, silo_id) {
        LOOP(ModuleId::COUNT, module_id) {
            LOOP(RpcServerId::COUNT, server_id) {
                _silos_context[silo_id].rpc_servers[module_id][server_id] = nullptr;
            }
        }
    }

    LOOP(_vmsg_configuration.n_silos, i) {
        SiloContext *ctx = &_silos_context[i];
        ctx->events_queue.init();
        ctx->seq_num = 0;
        ctx->acks_pool.init(n_acks, sizeof(MsgId));
        ctx->pending_acks_list_pool.init(n_acks);
        ctx->fiber = nullptr;
        ctx->n_pending_requests = 0;
        LOOP(MAX_ENVS, i) {
            ctx->pending_acks_anchors[i].init();
            ctx->pending_acks_lists[i].init(&ctx->pending_acks_anchors[i], &ctx->pending_acks_list_pool);
            ctx->n_acks[i] = 0;
        }
    }

    _last_req_time = get_time_nano();
}

static void vmsg_poll_fiber(void *vmsg)
{
    VMsg *p_vmsg = (VMsg *) vmsg;
    while (true) {
        p_vmsg->poll();
        P::Fiber::yield();
        if (unlikely(env_stop)) {
            break;
        }
    }
}

void VMsg::start_silo_fiber()
{
    const SiloId silo_id = Silo::get_current_silo_id();
    SiloContext *ctx = &_silos_context[silo_id];
    ctx->fiber = Fiber::init((Index)FiberGroupId::P_VMSG_POLLING, vmsg_poll_fiber, this, false);
    ASSERT_NOT_NULL(ctx->fiber);
    ctx->n_pending_requests = 0;
}

void VMsg::destroy()
{
    LOOP(_vmsg_configuration.n_silos, i) {
        SiloContext *ctx = &_silos_context[i];
        // not calling destroy since it is legit to go down with pending acks
        LOOP(MAX_ENVS, i) {
            // ctx->pending_acks_lists[i].destroy();
            // ctx->pending_acks_anchors[i].destroy();
        }
        ctx->pending_acks_list_pool.destroy();
        ctx->acks_pool.destroy();
        ctx->events_queue.destroy();
    }
    delete[] _silos_context;

    _rdma_transport.destroy();
    _address_table.destroy();
    _vmsg_pool.destroy();
    _poll_lock.destroy();
}

VMsgRes VMsg::start()
{
    VMsgRes res = _rdma_transport.start();
    if (res != VMsgRes::OK) {
        return res;
    }
    _vmsg_pool.register_buffers(&_rdma_transport);
    post_recv_buffers(BufferType::SERVER);
    post_recv_buffers(BufferType::REPLY);
    connect_to_peers();

    _started = true;
    return VMsgRes::OK;
}

void VMsg::stop()
{
    _vmsg_pool.unregister_buffers(&_rdma_transport);
    _rdma_transport.stop();
}

void VMsg::set_env_addresses(EnvId env_id, EnvAddresses *addresses)
{
    _address_table.set(env_id, addresses);
    if (_started && addresses->n_addr > 0) {
        connect_to_peer_modules(env_id);
    }
}

void VMsg::register_server(RpcServer *server, SiloId silo_id, ModuleId module_id)
{
    RpcServerId server_id = server->get_server_id();
    ASSERT(_silos_context[silo_id].rpc_servers[(int)module_id][(int)server_id] == nullptr);
    _silos_context[silo_id].rpc_servers[(int)module_id][(int)server_id] = server;
}

RpcServer *VMsg::get_rpc_server(VMsgHeader *header)
{
    SiloId silo_id = header->dest.silo_id;
    DEBUG_ASSERT(silo_id == Silo::get_current_silo_id());
    uint8_t module_id = header->dest.module_id;
    uint8_t server_id = header->server_id;
    return _silos_context[silo_id].rpc_servers[(int)module_id][(int)server_id];
}

VMsgRes VMsg::request_connection(EnvId env_id, ModuleId module_id, TransportType transport_type)
{
    ASSERT(transport_type == TransportType::RDMA, "RDMA is the only support transport type");
    return _rdma_transport.request_connection(env_id, module_id);
}

void VMsg::add_module_pair(ModuleId client, ModuleId server, TransportType transport_type)
{
    ASSERT(transport_type == TransportType::RDMA, "RDMA is currently the only supported transport type");
    _module_pairs[(int)client][(int)server] = transport_type;
    connect_to_peers();
}

void VMsg::connect_to_peers()
{
    LOOP(MAX_ENVS, env_id) {
        if (_address_table.has_addresses(env_id)) {
            PT_INFO(DATA, "connecting to env_id=%lu", env_id);
            connect_to_peer_modules(env_id);
        }
    }
}

void VMsg::connect_to_peer_modules(EnvId env_id)
{
    LOOP(ModuleId::COUNT, i) {
        LOOP(ModuleId::COUNT, j) {
            if ((_module_pairs[i][j] != TransportType::NONE) &&
                (!_rdma_transport.is_client_connected(env_id, (ModuleId)j))) {
                request_connection(env_id, (ModuleId)j, _module_pairs[i][j]);
            }
        }
    }
}

void VMsg::post_recv_buffers(BufferType buffer_type)
{
    MsgId msg_id;
    LOOP(ModuleId::COUNT, i) {
        ModuleId module_id = (ModuleId)i;
        void *buffer = _vmsg_pool.alloc(buffer_type, module_id, P::INVALID_INDEX);
        while (buffer != nullptr) {
            msg_id.buffer_index = (uint16_t)_vmsg_pool.address_to_index(buffer_type, module_id, buffer);
            msg_id.buffer_type = (uint8_t)buffer_type;
            msg_id.module_id = (uint8_t)i;
            post_recv_buffer(msg_id, buffer);
            buffer = _vmsg_pool.alloc(buffer_type, module_id, P::INVALID_INDEX);
        }
    }
}

void VMsg::post_recv_buffer(MsgId msg_id, void *buffer)
{
#ifdef DEBUG
    memset(buffer, 0, sizeof(VMsgHeader) + RPC_BUFFER_SIZE);
#endif
    const ModuleId module_id = (const ModuleId)msg_id.module_id;
    BufferType buffer_type = (BufferType)msg_id.buffer_type;
    MemRegion *region = _vmsg_pool.get_region(buffer_type, module_id);
    if (buffer_type == BufferType::SERVER) {
        _rdma_transport.recv_request(module_id, region, msg_id, buffer, RPC_BUFFER_SIZE);
    } else {
        _rdma_transport.recv_reply(module_id, region, msg_id, buffer, RPC_BUFFER_SIZE);
    }
}

static uint32_t msg_len(VMsgHeader *header)
{
    uint32_t len = sizeof(*header) + header->payload_size + header->tail_size;
    DEBUG_ASSERT(len <= RPC_BUFFER_SIZE);
    return len;
}

void *VMsg::alloc()
{
    ModuleId module_id = Fiber::get_module_id();
    void *buffer = _vmsg_pool.alloc(BufferType::REQUEST, module_id, Silo::get_current_silo_id());
    if (buffer == nullptr) {
        return nullptr;
    }
    VMsgHeader *header = (VMsgHeader *)buffer;
    memset(header, 0, sizeof(*header));
    header->sender.module_id = (uint8_t) module_id;

    return VMsgPool::msg_header_to_payload(header);
}

void VMsg::add_ack(MsgId *id, SiloId silo_id, EnvId env_id)
{
    SiloContext *ctx = &_silos_context[silo_id];
    Index ack_index = ctx->pending_acks_lists[env_id].pop();
    DEBUG_ASSERT(ack_index != List::Anchor::ANCHOR_INIT);
    MsgId *ack_id = (MsgId *)ctx->acks_pool.index_to_address(ack_index);
    TRACE_MSG_ID("add ack", (*ack_id));
    *id = *ack_id;
    ctx->acks_pool.free(ack_index);
    ctx->n_acks[env_id]--;
}

void VMsg::add_piggyback_acks(VMsgHeader *header, const SiloId silo_id)
{
    SiloContext *ctx = &_silos_context[silo_id];
    header->msg_ack.buffer_type = (uint8_t)BufferType::COUNT;
    EnvId env_id = header->dest.env_id;
    if (ctx->n_acks[env_id] == 0) {
        return;
    }
    uint32_t free_space = RPC_BUFFER_SIZE - header->payload_size;
    // if there is only 1 ack to pass, use the header piggyback field
    if (ctx->n_acks[env_id] == 1 || (free_space < sizeof(PiggybackData))) {
        add_ack(&header->msg_ack, silo_id, env_id);
        return;
    }
    // more than 1 ack to send, add piggyback information
    uint16_t acks_to_send = P_MIN(ctx->n_acks[env_id], free_space / sizeof(MsgId));
    PiggybackData *data = VMsgPool::msg_header_to_piggyback(header);
    data->type = PiggybackType::MSG_ACKS;
    data->acks.n_acks = acks_to_send;
    LOOP(acks_to_send, i) {
        add_ack(&data->acks.acks[i], silo_id, env_id);
    }
    header->tail_size = sizeof(*data) + (sizeof(MsgId) * acks_to_send);
}

void VMsg::handle_piggyback_data(VMsgHeader *header, SiloId silo_id)
{
    if (header->msg_ack.buffer_type != (uint8_t)BufferType::COUNT) {
        TRACE_MSG_ID("got ack", header->msg_ack);
        free_msg(silo_id, header->msg_ack);
    }
    if (header->tail_size > 0) {
        PiggybackData *data = VMsgPool::msg_header_to_piggyback(header);
        PT_DEBUG(DATA, "Freeing %u messages", data->acks.n_acks);
        if (data->type == PiggybackType::MSG_ACKS) {
            LOOP(data->acks.n_acks, i) {
                TRACE_MSG_ID("got ack", data->acks.acks[i]);
                free_msg(silo_id, data->acks.acks[i]);
            }
        } else {
            // not panicking under the assumption that one day there might be new types add
            PT_DEBUG(DATA, "unknown piggyback type %u, ignoring", data->type);
        }
    }
}

VMsgRes VMsg::send_request(VMsgHeader *header, uint64_t timeout_usec)
{
    const ModuleGUID dest = header->dest;
    MemRegion *region = _vmsg_pool.get_region(BufferType::REQUEST, (ModuleId) dest.module_id);
    VMsgRes res = _rdma_transport.send_request(dest, region, header->sender_msg_id, header, msg_len(header));
    if (res == VMsgRes::NOT_CONNECTED && timeout_usec > 0) {
        PT_INFO(DATA, "no connection to destination env_id=%hu module_id=%hhu retrying send", dest.env_id, dest.module_id);
        uint64_t now = 0;
        uint64_t start_time = NANO_TO_MICRO(get_time_nano());
        // wait for the send timeout for the link to get connected
        do {
            // Note: this should be done in a more efficient manner and avoid blocking async sends
            TimerQueues::fast_sleep(1000);
            res = _rdma_transport.send_request(dest, region, header->sender_msg_id, header, msg_len(header));
            now = NANO_TO_MICRO(get_time_nano());
        } while (res == VMsgRes::NOT_CONNECTED && (now - start_time) < timeout_usec);
    }
    if (res != VMsgRes::OK) {
        PT_ERROR(DATA, "failed to send message res=%d", res);
        return res;
    }
    return VMsgRes::OK;
}

VMsgRes VMsg::send_async(ModuleGUID dest_guid, RpcServerId server_id, uint8_t op_id,
                         uint64_t timeout_usec, void *buffer, uint16_t len, VMsgFuture **future)
{
    ASSERT(len <= RPC_BUFFER_SIZE);

    VMsgHeader *header = VMsgPool::msg_payload_to_header(buffer);
    PendingMsg *pending_msg = VMsgPool::msg_header_to_pending_msg(header);
    pending_msg->send_time_usec = NANO_TO_MICRO(get_time_nano());
    pending_msg->timeout_usec = timeout_usec;
    // verify that the buffer was allocated with the correct module id
    const SiloId silo_id = Silo::get_current_silo_id();
    header->sender.env_id = _vmsg_configuration.local_env_id;
    header->sender.silo_id = silo_id;
    DEBUG_ASSERT(header->sender.silo_id != Silo::INVALID_SILO_ID);
    header->dest = dest_guid;
    header->sender_msg_id = {
        .buffer_index = (uint16_t)_vmsg_pool.address_to_index(BufferType::REQUEST, (ModuleId) header->sender.module_id, header),
        .module_id = (uint8_t)header->sender.module_id,
        .buffer_type = (uint8_t)BufferType::REQUEST,
    };
    header->response_msg_id = {0};
    header->payload_size = len;
    header->verifier = 0;
    header->server_id = (uint8_t) server_id;
    header->op_id = op_id;
    header->tail_size = 0;
    header->seq_num = _silos_context[silo_id].seq_num++;
    add_piggyback_acks(header, silo_id);

    TRACE_VMSG_HEADER("send header", header);
    VMsgRes res = send_request(header, timeout_usec);
    if (res != VMsgRes::OK) {
        free_msg(silo_id, header->sender_msg_id);
        return res;
    }
    if (++_silos_context[silo_id].n_pending_requests == 1) {
        Provider::wakeup_if_sleeping(_silos_context[silo_id].fiber);
    }

    pending_msg->future.init();
    *future = &pending_msg->future;
    return VMsgRes::OK;
}

VMsgRes VMsg::send_sync(ModuleGUID dest_guid, RpcServerId server_id, uint8_t op_id, uint64_t timeout_usec,
                        void *buffer, uint16_t len, void **reply, uint32_t *reply_len)
{
    VMsgFuture *future;
    VMsgRes res = send_async(dest_guid, server_id, op_id, timeout_usec, buffer, len, &future);
    if (res != VMsgRes::OK) {
        return res;
    }

    future->wait();
    *reply = future->buffer;
    if (reply_len) {
        *reply_len = future->len;
    }
    return VMsgRes::OK;
}

void VMsg::handle_transport_events()
{
    if (!_poll_lock.try_lock()) {
        return;
    }

    bool should_sleep = false;
    uint64_t now = get_time_nano();
    TransportEvent events[RDMATransport::MAX_EVENTS_PER_POLL];
    int n_events = _rdma_transport.tpoll(events, NUM_ELEMENTS(events));
    if (n_events == 0) {
        if (NANO_TO_MILLI(now - _last_req_time) > Provider::IDLE_TIME_MILLI) {
            should_sleep = true;
            LOOP(_vmsg_configuration.n_silos, i) {
                SiloContext *ctx = &_silos_context[i];
                if (ctx->n_pending_requests > 0) {
                    should_sleep = false;
                    break;
                }
            }
        }
    } else {
        _last_req_time = now;
        for (int i = 0; i < n_events; ++i) {
            handle_event(&events[i]);
        }
    }

    _poll_lock.unlock();

    if (should_sleep) {
        TimerQueues::sleep(Provider::IDLE_SLEEP_INTERVAL);
    }
}

void VMsg::poll()
{
    handle_transport_events();
    handle_silo_events();
}

void VMsg::handle_event(TransportEvent *event)
{
//    PT_DEBUG(DATA, "Got event type=%d status=%d len=%u",
//               event->type, event->status, event->len);
//    TRACE_MSG_ID("event msg_id", event->id);
    switch (event->type) {
        case TransportEvent::Type::WRITE_COMPLETE:
            on_write_complete(event);
            break;
        case TransportEvent::Type::READ_COMPLETE:
            on_read_complete(event);
            break;
        case TransportEvent::Type::SEND_COMPLETE:
            on_send_complete(event);
            break;
        case TransportEvent::Type::MSG_RECV:
            on_msg_recv(event);
            break;
    }
}

void VMsg::on_write_complete(TransportEvent *event)
{
    PANIC("not implemented");
}

void VMsg::on_read_complete(TransportEvent *event)
{
    PANIC("not implemented");
}

void VMsg::on_send_complete(TransportEvent *event)
{
    PT_DEBUG(DATA, "send complete");
}

void VMsg::on_msg_recv(TransportEvent *event)
{
    const MsgId id = event->id;
    void *buffer = _vmsg_pool.msg_id_to_address(id);
    if (event->status != VMsgRes::OK) {
        PT_ERROR(DATA, "got recv failure status=%d", event->status);
        // post buffer again
        post_recv_buffer(event->id, buffer);
        return;
    }

    // queue the message on the relevant silo queue
    ASSERT(event->len >= sizeof(VMsgHeader));
    VMsgHeader *header = (VMsgHeader *)buffer;
    TRACE_VMSG_HEADER("msg rcv header", header);
    QueuedEvent *queued_event = VMsgPool::msg_header_to_queued_event(header);
    queued_event->id = id;
    SiloId silo_id = header->dest.silo_id;
    ASSERT(silo_id < _vmsg_configuration.n_silos);
    Index idx;
    memcpy(&idx, &id, sizeof(MsgId));
    _silos_context[silo_id].events_queue.push(&queued_event->node, idx);
}

#define INDEX_TO_MSG_ID(IDX) (*(MsgId*)(void*)(&IDX))

static SPSCQueue::Node *get_node(VMsgPool *pool, Index index)
{
    MsgId id = INDEX_TO_MSG_ID(index);
    VMsgHeader *header = (VMsgHeader *)pool->msg_id_to_address(id);
    return &(VMsgPool::msg_header_to_queued_event(header)->node);
}

#define GET_NODE(IDX) \
    get_node(&_vmsg_pool, IDX)

void VMsg::handle_silo_events()
{
    SiloId silo_id = Silo::get_current_silo_id();
    SPSCQueue *silo_queue = &_silos_context[silo_id].events_queue;
    SPSC_QUEUE_ITER(silo_queue, GET_NODE, index) {
        MsgId index_id;
        memcpy(&index_id, &index, sizeof(MsgId));
        VMsgHeader *header = (VMsgHeader *)_vmsg_pool.msg_id_to_address(index_id);
        QueuedEvent *event = VMsgPool::msg_header_to_queued_event(header);
        ASSERT_NOT_NULL(header);
        ASSERT_EQUAL(header->dest.silo_id, silo_id);
        handle_piggyback_data(header, silo_id);
        MsgId id = event->id;
        if (id.buffer_type == (uint8_t)BufferType::SERVER) {
            handle_incoming_msg(header);
        } else if (id.buffer_type == (uint8_t)BufferType::REPLY) {
            handle_reply(header, silo_id);
        } else {
            PANIC("invalid buffer type");
        }
    }
}

void VMsg::free_msg(SiloId silo_id, MsgId id)
{
    _vmsg_pool.free((BufferType)id.buffer_type, (ModuleId)id.module_id, silo_id, id.buffer_index);
}


void VMsg::execute_incoming_request(VMsgHeader *request_header)
{
    TRACE_VMSG_HEADER("incoming request", request_header);

    SiloId silo_id = request_header->dest.silo_id;
    ModuleId module_id = (ModuleId) request_header->dest.module_id;

    VMsgHeader *response = (VMsgHeader *)_vmsg_pool.alloc(BufferType::RESPONSE, module_id, silo_id);
    ASSERT(response != nullptr);

    // call server
    RpcServer *server = get_rpc_server(request_header);
    DEBUG_ASSERT(server != nullptr);
    server->run_op(request_header->op_id, VMsgPool::msg_header_to_payload(request_header), request_header->payload_size,
                   VMsgPool::msg_header_to_payload(response), &response->payload_size);

    PendingMsg *pending_response = VMsgPool::msg_header_to_pending_msg(response);
    pending_response->send_time_usec = NANO_TO_MICRO(get_time_nano());
    pending_response->timeout_usec = RESPONSE_TIMEOUT_USEC;
    MsgId response_msg_id = {
        .buffer_index = (uint16_t)_vmsg_pool.address_to_index(BufferType::RESPONSE,
                                                              (ModuleId) request_header->dest.module_id, response),
        .module_id = (uint8_t)module_id,
        .buffer_type = (uint8_t)BufferType::RESPONSE,
    };

    MemRegion *region = _vmsg_pool.get_region(BufferType::RESPONSE, module_id);

    response->sender = request_header->dest;
    response->dest = request_header->sender;
    response->seq_num = request_header->seq_num;
    response->sender_msg_id = request_header->sender_msg_id;
    response->response_msg_id = response_msg_id;
    response->verifier = 0;
    response->server_id = request_header->server_id;
    response->op_id = request_header->op_id;
    response->tail_size = 0;
    add_piggyback_acks(response, silo_id);

    VMsgRes res = _rdma_transport.send_response(response->dest, region, response_msg_id, response, msg_len(response));
    if (res != VMsgRes::OK) {
        PT_ERROR(DATA, "failed to send response res=%d", res);
        _vmsg_pool.free_address(BufferType::RESPONSE,
                                module_id,
                                silo_id, response);
    }

    // done with the server buffer
    QueuedEvent *event = VMsgPool::msg_header_to_queued_event(request_header);
    post_recv_buffer(event->id, request_header);
}

static void handle_incoming_msg_func(void *request_header)
{
    Env::get()->get_vmsg()->execute_incoming_request((VMsgHeader *)request_header);
}

void VMsg::handle_incoming_msg(VMsgHeader *request_header)
{
    // create a fiber to execute the request
    RpcServer *server = get_rpc_server(request_header);
    ASSERT(server != nullptr);
    FiberGroupId fiber_group_id = server->get_op_fiber_group(request_header->op_id);
    Fiber *fiber = P::Fiber::init((Index)fiber_group_id, handle_incoming_msg_func, request_header, false);
    ASSERT_NOT_NULL(fiber);
}

void VMsg::handle_reply(VMsgHeader *header, SiloId silo_id)
{
    PT_DEBUG(DATA, "handling reply for silo_id=%hhu seq_num=%hu ", header->dest.silo_id, header->seq_num);
    TRACE_VMSG_HEADER("reply header", header);
    VMsgHeader *pending_header = (VMsgHeader *)_vmsg_pool.msg_id_to_address(header->sender_msg_id);
    PendingMsg *pending_msg = VMsgPool::msg_header_to_pending_msg(pending_header);
    pending_msg->future.buffer = VMsgPool::msg_header_to_payload(header);
    pending_msg->future.len = header->payload_size;
    pending_msg->future.set();

    // add ack to pending acks list
    SiloContext *ctx = &_silos_context[silo_id];
    MsgId *ack_id = (MsgId *)ctx->acks_pool.alloc_address();
    ASSERT_NOT_NULL(ack_id);
    *ack_id = header->response_msg_id;
    const EnvId env_id = header->sender.env_id;
    ctx->pending_acks_lists[env_id].append(ctx->acks_pool.address_to_index(ack_id));
    ctx->n_acks[env_id]++;
    PT_DEBUG(DATA, "add ack - silo_id=%hhu env_id=%hu n_acks=%u", silo_id, env_id, ctx->n_acks[env_id]);
    --ctx->n_pending_requests;
}

void VMsg::free_reply(void *reply_buffer)
{
    const SiloId current_silo_id = Silo::get_current_silo_id();
    VMsgHeader *header = VMsgPool::msg_payload_to_header(reply_buffer);
    const MsgId sender_msg_id = header->sender_msg_id;
    // free request buffer
    free_msg(current_silo_id, sender_msg_id);
    // return the reply buffer to the recv queue
    MsgId reply_id = {
        .buffer_index = (uint16_t)_vmsg_pool.address_to_index(BufferType::REPLY, (ModuleId) header->dest.module_id, header),
        .module_id = (uint8_t)header->dest.module_id,
        .buffer_type = (uint8_t)BufferType::REPLY,
    };
    post_recv_buffer(reply_id, header);
}

}
}
