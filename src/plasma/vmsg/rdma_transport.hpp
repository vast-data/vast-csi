/* Copyright (C) Vast Data Ltd. */

/*!
 * \file rdma_transport.hpp
 * \brief The messaging infrastructure RDMA transport layer, responsible for managing RDMA connections and RDMA data
 *        operations.
 */

#pragma once

#include <semaphore.h>
#include "vmsg_defs.hpp"
#include "rdma_link.hpp"
#include "plasma/utils/compiler.hpp"
#include "plasma/data/queue.hpp"
#include "plasma/sync/spin_lock.hpp"
#include "address_table.hpp"
#include "connection.hpp"

namespace P {
namespace VMsg {

typedef struct MemRegion MemRegion;

class RDMATransport {
public:
    /*!
     * Initialize the RDMA transport.
     * /param local_env_id the id of the env we are running in
     * /param pointer to an initialized address table containing the addresses of env we connect too
     */
    void init(VMsgConfiguration *vmsg_configuration, AddressTable *addr_table);
    void destroy();
    VMsgRes start();
    void stop();

    /*!
     * Request to connect to the given module at the given env
     */
    VMsgRes request_connection(EnvId env_id, ModuleId module_id);

    /*!
     * Returns true if there is a client connection to the specified module at the specified env
     */
    bool is_client_connected(EnvId env_id, ModuleId module_id);

    /*!
     * Returns true if there is a server connection to the specified module at the specified env
     */
    bool is_server_connected(EnvId env_id, ModuleId module_id);

    /*!
     * Register the given memory region so it can be later used for rdma operations
     *
     * /return a handle for the registered memory
     */
    MemRegion *register_mem(void *buff, size_t len);

    /*!
     * Unregister a previously registered memory region
     */
    VMsgRes unregister_mem(MemRegion *region);

    /*!
     * Queue the given buffer for receiving requests for the given module. The buffer must be placed inside the given
     * memory region.
     *
     * /param module_id the module to queue the buffer for
     * /param region the previously registered handle for the memory region the buffer belongs too
     * /param msg_id the buffer identifier
     * /param buff a pointer to the buffer address
     * /param len the buffer length
     */
    VMsgRes recv_request(ModuleId module_id, MemRegion *region, MsgId msg_id, void *buff, uint32_t len);

    /*!
     * Queue the given buffer for receiving replies for the given module. The buffer must be placed inside the given
     * memory region.
     *
     * /param module_id the module to queue the buffer for
     * /param region the previously registered handle for the memory region the buffer belongs too
     * /param msg_id the buffer identifier
     * /param buff a pointer to the buffer address
     * /param len the buffer length
     */
    VMsgRes recv_reply(ModuleId module_id, MemRegion *region, MsgId msg_id, void *buff, uint32_t len);

    /*!
     * Send a request to the env/module/silo as specified in module_guid. The given buffer must be placed inside the
     * given memory region.
     *
     * /param module_guid the send destination
     * /param region the previously registered handle for the memory region the buffer belongs too
     * /param msg_id the buffer identifier
     * /param buff a pointer to the buffer address
     * /param len the buffer length
     */
    VMsgRes send_request(ModuleGUID module_guid, MemRegion *region, MsgId msg_id, void *buff, uint32_t len);

    /*!
     * Send a reply to the env/module/silo as specified in module_guid. The given buffer must be placed inside the
     * given memory region.
     *
     * /param module_guid the send destination
     * /param region the previously registered handle for the memory region the buffer belongs too
     * /param msg_id the buffer identifier
     * /param buff a pointer to the buffer address
     * /param len the buffer length
     */
    VMsgRes send_response(ModuleGUID module_guid, MemRegion *region, MsgId msg_id, void *buff, uint32_t len);

    static const uint32_t MAX_EVENTS_PER_POLL = 16;

    /*!
     * Poll for transport events
     *
     * /param events a pointer for placing the transport events
     * /param max_events the maximal number of events to return, in any case no more than MAX_EVENTS_PER_POLL will be returned
     * from a single call
     *
     * /return the number of events polled or -1 in case of an error
     */
    int tpoll(TransportEvent *events OUT, uint32_t max_events IN);

private:
    // event processing methods
    static void *event_loop_func(void *arg);
    void event_loop();
    void handle_connection_requests();
    void handle_event(struct rdma_cm_event *event);
    void on_addr_resolved(struct rdma_cm_event *event);
    void on_route_resolved(struct rdma_cm_event *event);
    void on_connect_request(struct rdma_cm_event *event);
    void on_connection_established(struct rdma_cm_event *event);

    VMsgRes recv(struct ibv_srq *srq, struct ibv_mr *mr, MsgId msg_id, void *buff, uint32_t len);

    VMsgRes create_device_resources(struct ibv_context *ibv_ctx);
    VMsgRes open_devices();

private:
    // max number of item in the completion queue
    static const uint32_t CQ_DEPTH = 4096;
    static const uint32_t MAX_CONN_REQUESTS = 64;

    AddressTable *_addr_table;
    VMsgConfiguration _vmsg_configuration;

    // connection requests queue
    P::Queue<ConnectionRequest> _conn_queue;
    P::Sync::SpinLock _conn_lock;

    // listen link per each address on this node
    RDMALink _listen_links[MAX_ADDR_PER_ENV];
    // outgoing connection per env / module
    Connection _client_connections[MAX_ENVS][MODULES_COUNT];
    // incoming connection per env / module
    Connection _server_connections[MAX_ENVS][MODULES_COUNT];

    // messages are received on shared receive queue that are partitioned per module in order to avoid deadlocks
    // shared receive queue per client module for receiving replies
    struct ibv_srq *_client_srqs[MODULES_COUNT];
    // shared receive queue per server module for accepting requests
    struct ibv_srq *_server_srqs[MODULES_COUNT];
    // event handling thread
    pthread_t _events_thread;

    // start sem used to wait for the first connection during startup
    sem_t _start_sem;
    // RDMA verbs objects
    struct ibv_context *_ibv_ctx;
    struct rdma_event_channel *_event_channel;
    struct ibv_pd *_pd;
    struct ibv_comp_channel *_comp_channel;
    struct ibv_cq *_cq;
    // stop flag
    bool _stop;
};

}
}
