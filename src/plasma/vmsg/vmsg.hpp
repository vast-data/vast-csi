/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "vmsg_defs.hpp"
#include "address_table.hpp"
#include "rdma_transport.hpp"
#include "vmsg_pool.hpp"
#include "rpc_server.hpp"
#include "plasma/data/spsc_queue.hpp"
#include "plasma/memory/cpool.hpp"
#include "plasma/utils/time.hpp"
#include "plasma/data/list.hpp"

namespace P {
namespace VMsg {

class VMsg {
public:
    /*!
     * Initialize the messaging infrastructure.
     * /param local_env_id the id of the env we are running in
     */
    void init(VMsgConfiguration *vmsg_configuration);
    void destroy();
    VMsgRes start();
    void stop();

    /*!
     * Initialize the provider fiber.
     */
    void start_silo_fiber();

    /*!
     * Set the addresses for the specified env
    */
    void set_env_addresses(EnvId env_id, EnvAddresses *addresses);

    /*!
     * Defines a connection pair between the client and server modules
     */
    void add_module_pair(ModuleId client, ModuleId server, TransportType transport_type);

    /*!
     * Register a module server
     */
    void register_server(RpcServer *server, SiloId silo_id, ModuleId module_id);

    /*!
     * Allocate a buffer that can be used for sending RPC messages, the usable buffer size is RPC_BUFFER_SIZE
     *
      * \return a buffer address or nullptr if no buffers are available
     */
    void *alloc();

    /*!
     * Low level API for sending a sync RPC request.
     * In the common case this API should only be used by auto generated code.
     */
    VMsgRes send_sync(ModuleGUID dest_guid, RpcServerId server_id, uint8_t op_id, uint64_t timeout_usec,
                      void *buffer, uint16_t len, void **reply, uint32_t *reply_len);

    /*!
     * Low level API for sending an async RPC request.
     * In the common case this API should only be used by auto generated code.
     */
    VMsgRes send_async(ModuleGUID dest_guid, RpcServerId server_id, uint8_t op_id, uint64_t timeout_usec,
                       void *buffer, uint16_t len, VMsgFuture **future);

    /*!
     * Low level API for freeing message replies allocated by the messaging infrastructure.
     * In the common case this API should only be used by auto generated code.
     */
    void free_reply(void *reply_buffer);

    // handle messaging events, should only be called by the poll fiber
    void poll();

    // execute an incoming request, should only be called by a fiber created by the messaging infra
    void execute_incoming_request(VMsgHeader *request_header);

private:
    void post_recv_buffers(BufferType buffer_type);
    void post_recv_buffer(MsgId msg_id, void *buffer);
    void connect_to_peers();
    void connect_to_peer_modules(EnvId env_id);
    // Request to connect to the given module at the given env
    VMsgRes request_connection(EnvId env_id, ModuleId module_id, TransportType transport_type);
    VMsgRes send_request(VMsgHeader *header, uint64_t timeout_usec);
    void handle_event(TransportEvent *event);
    void on_write_complete(TransportEvent *event);
    void on_read_complete(TransportEvent *event);
    void on_send_complete(TransportEvent *event);
    void on_msg_recv(TransportEvent *event);
    void handle_incoming_msg(VMsgHeader *header);
    void handle_reply(VMsgHeader *header, SiloId silo_id);
    void handle_transport_events();
    void handle_silo_events();
    void free_msg(SiloId silo_id, MsgId id);
    void add_piggyback_acks(VMsgHeader *header, const SiloId silo_id);
    void handle_piggyback_data(VMsgHeader *header, SiloId silo_id);
    void add_ack(MsgId *id, SiloId silo_id, EnvId env_id);
    RpcServer *get_rpc_server(VMsgHeader *header);

private:
    static const uint64_t RESPONSE_TIMEOUT_USEC = MICRO_TO_SEC(60);

    struct SiloContext {
        // modules RPC servers
        RpcServer *rpc_servers[MODULES_COUNT][(int)RpcServerId::COUNT];

        SPSCQueue events_queue;
        uint16_t seq_num;

        // lists for pending acks
        List::Pool pending_acks_list_pool;
        List::Anchor pending_acks_anchors[MAX_ENVS];
        List pending_acks_lists[MAX_ENVS];
        uint32_t n_acks[MAX_ENVS];

        Pool acks_pool;

        Fiber *fiber;
        uint32_t n_pending_requests;
    };

    SiloContext *_silos_context;

    bool _started;
    AddressTable _address_table;
    VMsgPool _vmsg_pool;
    RDMATransport _rdma_transport;
    // a map of the modules that are allowed to communicate
    TransportType _module_pairs[MODULES_COUNT][MODULES_COUNT];
    // lock for polling transports
    Sync::SpinLock _poll_lock;
    VMsgConfiguration _vmsg_configuration;
    uint64_t _last_req_time;  // nano
};  // class VMsg

}  // namespace VMsg
}  // namespace P {
