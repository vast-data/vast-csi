/* Copyright (C) Vast Data Ltd. */

/*!
 * \file rdma_link.hpp
 * \brief Represent a concrete communication link between 2 Environments on top of RDMA.
 */

#pragma once

#include <stdint.h>
#include <stdio.h>
#include <netdb.h>
#include "vmsg_defs.hpp"

namespace P {
namespace VMsg {

enum class LinkState {
    IDLE,
    ADDR_RESOLVE_REQUEST,
    ADDR_RESOLVED,
    ROUTE_RESOLVED,
    CONNECT_REQUEST,
    CONNECTED,
    LISTEN,
    ERROR,

    COUNT
};

enum class LinkType {
    SEND_REQUEST,
    RECV_REQUEST,
    SEND_RESPONSE,
    RECV_RESPONSE,
    LISTEN,

    COUNT
};

class RDMALink {
public:
    void init(EnvId env_id, ModuleId module_id, LinkType link_type);
    void destroy();
    void reset();


    /*!
     * Set the link to listen for incoming connection requests
     */
    VMsgRes listen(struct rdma_event_channel *channel, const char *host, uint16_t port);

    /*!
     * Initiate a connection to the requested address (client side).
     */
    VMsgRes initiate_connection(struct rdma_event_channel *channel, const char *host, uint16_t port);

    /*!
     * Establish connection with the requested address.
     * For client links this is called once the route to the server is resolved following a call to initiate_connection
     * For server links this is called when a connection request is received by a listen link
     */
    VMsgRes establish_connection(EnvId local_env_id, struct ibv_cq *cq, struct ibv_pd *pd, struct ibv_srq *srq);

    /*!
     * Send message on top of the link QP, the link must be connected.
     */
    VMsgRes send(struct ibv_mr *mr, MsgId msg_id, void *buff, uint32_t len);

    void set_state(LinkState state)
    {
        verify_state_transition(state);
        _state = state;
    }

    LinkState get_state() const { return _state; }
    bool is_client_link() const { return _link_type == LinkType::SEND_REQUEST || _link_type == LinkType::SEND_RESPONSE; }
    ConnDir get_link_direction() const;
    void set_cm_id(struct rdma_cm_id *cm_id);
    ModuleId get_module_id() const { return _module_id; }
    EnvId get_env_id() const { return _env_id; }

private:

    typedef bool StateMatrix[(int)LinkState::COUNT][(int)LinkState::COUNT];
    static StateMatrix *_state_trans;
    static StateMatrix *init_state_transition();
    void verify_state_transition(LinkState link_state);

    // Max backlog size of incoming connection requests.
    static const uint16_t LISTEN_BACKLOG = 32;
    // number of outstanding send QP requests
    static const uint32_t RQ_SEND_DEPTH = 16;
    // The maximum number of scatter/gather elements in any Work Request that can be posted to the
    // Send Queue in that Queue Pair.
    static const uint32_t MAX_SEND_SGE = 1;
    // The maximum number of outstanding RDMA read and atomic operations that the local side will have to
    // the remote side.
    static const uint8_t CONN_SEND_DEPTH = 16;
    // The  maximum  number of outstanding RDMA read and atomic operations that the local side will accept from
    // the remote side.
    static const uint8_t CONN_RECV_DEPTH = 16;
    // The maximum number of times that a data transfer operation should be retried on the connection
    // when an error occurs.
    static const uint8_t SEND_ERROR_RETRY_COUNT = 8;
    // The maximum number of times that a send operation from the remote peer should be retried on a connection after
    // receiving a receiver not ready (RNR) error.  RNR errors are generated when a send request arrives before a
    // buffer has been posted to receive the incoming data.
    static const uint8_t SEND_RNR_RETRY_COUNT = 32;

    struct rdma_cm_id *_cm_id;
    LinkState _state;
    LinkType _link_type;
    ModuleId _module_id;
    EnvId _env_id;
};

}
}
