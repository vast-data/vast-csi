#include <netdb.h>
#include <rdma/rdma_cma.h>
#include "rdma_link.hpp"
#include "plasma/internal.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/utils/assert.hpp"

namespace P {
namespace VMsg {

void RDMALink::init(EnvId env_id, ModuleId module_id)
{
    _env_id = env_id;
    _module_id = module_id;
    _state = LinkState::IDLE;
    _cm_id = nullptr;
    _client_link = false;
}

void RDMALink::destroy()
{
    if (_cm_id) {
        if (_cm_id->qp) {
            ibv_destroy_qp(_cm_id->qp);
        }
        rdma_destroy_id(_cm_id);
    }
    _state = LinkState::IDLE;
}


void RDMALink::reset()
{
    destroy();
    init(_env_id, _module_id);
}

static struct addrinfo *get_addr(const char *host, uint16_t port)
{
    char portstr[64];
    snprintf(portstr, sizeof(portstr), "%u", port);
    struct addrinfo *addr;
    int ret = getaddrinfo(host, portstr, NULL, &addr);
    if (ret) {
        PT_ERROR("getaddrinfo failed - invalid hostname or IP address");
        return NULL;
    }
    return addr;
}

VMsgRes RDMALink::listen(struct rdma_event_channel *channel, const char *host, uint16_t port)
{
    int ret = rdma_create_id(channel, &_cm_id, this, RDMA_PS_TCP);
    if (ret) {
        PT_ERROR("rdma_create_id failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    struct addrinfo *addr = get_addr(host, port);
    if (addr == NULL) {
        PT_ERROR("get_addr failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    ret = rdma_bind_addr(_cm_id, addr->ai_addr);
    freeaddrinfo(addr);
    if (ret) {
        PT_ERROR("rdma_bind_addr errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    ret = rdma_listen(_cm_id, LISTEN_BACKLOG);
    if (ret) {
        PT_ERROR("rdma_listen failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    set_state(LinkState::LISTEN);

    PT_DEBUG("created listen link cm_id=%p listening on port=%hd", _cm_id, ntohs(rdma_get_src_port(_cm_id)));
    return VMsgRes::OK;
}


VMsgRes RDMALink::initiate_connection(rdma_event_channel *channel, const char *host, uint16_t port)
{
    ASSERT(_state == LinkState::IDLE);

    _client_link = true;

    int ret = rdma_create_id(channel, &_cm_id, this, RDMA_PS_TCP);
    if (ret) {
        PT_ERROR("rdma_create_id failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    struct addrinfo *addr = get_addr(host, port);
    if (addr == NULL) {
        PT_ERROR("get_addr  failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    ret = rdma_resolve_addr(_cm_id, NULL, addr->ai_addr, RESOLVE_TIMEOUT_MS);
    freeaddrinfo(addr);
    if (ret) {
        PT_ERROR("rdma_resolve_addr failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    set_state(LinkState::ADDR_RESOLVE_REQUEST);

    return VMsgRes::OK;
}

VMsgRes RDMALink::establish_connection(EnvId local_env_id, struct ibv_cq *cq, struct ibv_pd *pd, struct ibv_srq *srq)
{
    DEBUG_ASSERT(cq != NULL);
    DEBUG_ASSERT(pd != NULL);
    DEBUG_ASSERT(srq != NULL);

    PT_DEBUG("src_port=%hu dst_port=%hu client=%c",
             ntohs(rdma_get_src_port(_cm_id)), ntohs(rdma_get_dst_port(_cm_id)), _client_link);

    PT_DEBUG("creating qp pd=%p cm_id=%p srq=%p cm_device=%p cm_device_name='%s'",
             pd, _cm_id, srq, _cm_id->verbs, ibv_get_device_name(_cm_id->verbs->device));
    struct ibv_qp_init_attr init_attr;
    memset(&init_attr, 0, sizeof(init_attr));
    init_attr.cap.max_send_wr = RQ_SEND_DEPTH;
    init_attr.cap.max_send_sge = MAX_SEND_SGE;
    init_attr.srq = srq;
    // the following 2 params are ignored when passing SRQ
    init_attr.cap.max_recv_wr = 0;
    init_attr.cap.max_recv_sge = 0;

    init_attr.qp_type = IBV_QPT_RC;
    init_attr.send_cq = cq;
    init_attr.recv_cq = cq;
    init_attr.qp_context = this;

    int ret = rdma_create_qp(_cm_id, pd, &init_attr);
    if (ret) {
        PT_ERROR("rdma_create_qp failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    struct rdma_conn_param cm_params;
    memset(&cm_params, 0, sizeof(cm_params));
    Handshake handshake = {
        .env_id = local_env_id,
        .module_id = _module_id,
        .module_ver = 0,
        .vmsg_ver = VMSG_VERSION
    };
    cm_params.private_data = &handshake;
    cm_params.private_data_len = sizeof(Handshake);
    cm_params.initiator_depth = CONN_SEND_DEPTH;
    cm_params.responder_resources = CONN_RECV_DEPTH;
    cm_params.retry_count = SEND_ERROR_RETRY_COUNT;
    cm_params.rnr_retry_count = SEND_RNR_RETRY_COUNT;
    if (_client_link) {
        PT_DEBUG("calling rdma_connect");
        ret = rdma_connect(_cm_id, &cm_params);
        if (ret) {
            PT_ERROR("rdma_connect  failed errno=%d", errno);
            set_state(LinkState::ERROR);
            return VMsgRes::CONNECTION_REFUSED;
        }
        set_state(LinkState::CONNECT_REQUEST);
    } else {
        PT_DEBUG("calling rdma_accept");
        ret = rdma_accept(_cm_id, &cm_params);
        if (ret) {
            PT_ERROR("rdma_accept  failed errno=%d", errno);
            set_state(LinkState::ERROR);
            return VMsgRes::SYS_ERR;
        }
        set_state(LinkState::CONNECTED);
    }

    PT_DEBUG("connected qp=%p", _cm_id->qp);
    return VMsgRes::OK;
}

void RDMALink::set_cm_id(rdma_cm_id *cm_id)
{
    ASSERT(_cm_id == NULL);
    _client_link = false;
    _cm_id = cm_id;
}

VMsgRes RDMALink::send(struct ibv_mr *mr, MsgId msg_id, void *buff, uint32_t len)
{
    if (get_state() != LinkState::CONNECTED) {
        return VMsgRes::NOT_CONNECTED;
    }

    struct ibv_sge sg;
    sg.addr = (uintptr_t)buff;
    sg.length = len;
    sg.lkey = mr->lkey;

    struct ibv_send_wr wr;
    memset(&wr, 0, sizeof(wr));
    static_assert(sizeof(msg_id) <= sizeof(wr.wr_id), "wr_id should be able to contain msg_id");
    memcpy(&wr.wr_id, &msg_id, sizeof(msg_id));
    wr.sg_list = &sg;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_SEND;
    wr.send_flags = 0;

    struct ibv_send_wr *bad_wr;
    int ret = ibv_post_send(_cm_id->qp, &wr, &bad_wr);
    if (ret) {
        PT_ERROR("ibv_post_send failed ret=%d qp=%p errno=%d", ret, _cm_id->qp, errno);
        return VMsgRes::SYS_ERR;
    }
    return VMsgRes::OK;
}

RDMALink::StateMatrix *RDMALink::_state_trans = init_state_transition();

#define ALLOW_TRANS(X, Y) \
    (*allowed_states)[(int)LinkState::X][(int)LinkState::Y] = true

RDMALink::StateMatrix *RDMALink::init_state_transition()
{
    StateMatrix *allowed_states = (StateMatrix *)malloc(sizeof(StateMatrix));
    memset(allowed_states, 0, sizeof(StateMatrix));

    // listen link
    ALLOW_TRANS(IDLE, LISTEN);

    // client link connection flow
    ALLOW_TRANS(IDLE, ADDR_RESOLVE_REQUEST);
    ALLOW_TRANS(ADDR_RESOLVE_REQUEST, ADDR_RESOLVED);
    ALLOW_TRANS(ADDR_RESOLVED, ROUTE_RESOLVED);
    ALLOW_TRANS(ROUTE_RESOLVED, CONNECT_REQUEST);
    ALLOW_TRANS(CONNECT_REQUEST, CONNECTED);

    // server link connection flow
    ALLOW_TRANS(IDLE, CONNECT_REQUEST);
    ALLOW_TRANS(CONNECT_REQUEST, CONNECTED);

    // error states
    ALLOW_TRANS(ADDR_RESOLVE_REQUEST, ERROR);
    ALLOW_TRANS(ADDR_RESOLVED, ERROR);
    ALLOW_TRANS(ROUTE_RESOLVED, ERROR);
    ALLOW_TRANS(CONNECT_REQUEST, ERROR);
    ALLOW_TRANS(LISTEN, ERROR);
    ALLOW_TRANS(CONNECTED, ERROR);

    return allowed_states;
}

void RDMALink::verify_state_transition(LinkState link_state)
{
    PT_DEBUG("Link - env_id=%hu module_id=%hhu state transition %d-->%d", _env_id, _module_id, _state, link_state);
    ASSERT((*_state_trans)[(int)_state][(int)link_state],
           "Illegal state transition from " << (int)_state << " to " << (int)link_state);
}

}
}
