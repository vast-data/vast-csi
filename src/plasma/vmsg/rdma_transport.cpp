#include <rdma/rdma_cma.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <netdb.h>
#include <cstdio>
#include <infiniband/verbs.h>
#include <poll.h>
#include <unistd.h>
#include "rdma_transport.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/sync/lock_guard.hpp"
#include "plasma/internal.hpp"
#include "plasma/trace/emitter.hpp"

using namespace P::Sync;

namespace P {
namespace VMsg {

void RDMATransport::init(VMsgConfiguration *vmsg_configuration, AddressTable *addr_table)
{
    _addr_table = addr_table;
    _vmsg_configuration = *vmsg_configuration;
    sem_init(&_start_sem, 0, 0);
    _conn_lock.init();
    _conn_queue.init(MAX_CONN_REQUESTS);

    for (int i = 0; i < NUM_ELEMENTS(_client_connections); ++i) {
        for (int j = 0; j < NUM_ELEMENTS(_client_connections[0]); ++j) {
            _client_connections[i][j].init(i, (ModuleId)j);
            _server_connections[i][j].init(i, (ModuleId)j);
        }
    }

    for (int k = 0; k < NUM_ELEMENTS(_listen_links); ++k) {
        // listen links are for all envs/modules
        _listen_links[k].init(MAX_ENVS, ModuleId::COUNT);
    }
    for (int k = 0; k < NUM_ELEMENTS(_client_srqs); ++k) {
        _client_srqs[k] = nullptr;
        _server_srqs[k] = nullptr;
    }

    _event_channel = nullptr;
    _pd = nullptr;
    _comp_channel = nullptr;
    _cq = nullptr;
    _ibv_ctx = nullptr;
}

void RDMATransport::destroy()
{
    ASSERT(_stop);
    _conn_queue.destroy();
    _conn_lock.destroy();

    for (int i = 0; i < NUM_ELEMENTS(_client_connections); ++i) {
        for (int j = 0; j < NUM_ELEMENTS(_client_connections[0]); ++j) {
            _client_connections[i][j].destroy();
            _server_connections[i][j].destroy();
        }
    }

    for (int k = 0; k < NUM_ELEMENTS(_listen_links); ++k) {
        _listen_links[k].destroy();
    }

    for (int k = 0; k < NUM_ELEMENTS(_client_srqs); ++k) {
        SAFE_DESTROY(_client_srqs[k], ibv_destroy_srq);
        SAFE_DESTROY(_server_srqs[k], ibv_destroy_srq);
    }
    SAFE_DESTROY(_cq, ibv_destroy_cq);
    SAFE_DESTROY(_comp_channel, ibv_destroy_comp_channel);
    SAFE_DESTROY(_pd, ibv_dealloc_pd);
    SAFE_DESTROY(_event_channel, rdma_destroy_event_channel);
    sem_destroy(&_start_sem);
}

/*static*/ void *RDMATransport::event_loop_func(void *arg)
{
    RDMATransport *trans = (RDMATransport *)arg;
    trans->event_loop();
    return NULL;
}

VMsgRes RDMATransport::start()
{
    _stop = false;
    _event_channel = rdma_create_event_channel();
    if (!_event_channel) {
        PT_ERROR("rdma_create_event_channel");
        return VMsgRes::SYS_ERR;
    }

    ASSERT(_addr_table->has_addresses(_vmsg_configuration.local_env_id), "no local addresses configured");

    _addr_table->lock();
    EnvAddresses *addresses = _addr_table->get(_vmsg_configuration.local_env_id);
    LOOP(addresses->n_addr, i) {
        EnvAddress *addr = &addresses->addresses[i];
        VMsgRes res = _listen_links[i].listen(_event_channel, addr->host, addr->port);
        ASSERT(res == VMsgRes::OK, "failed to listen on " << addr->host << ":" << addr->port);
    }
    _addr_table->unlock();

    int ret = pthread_create(&_events_thread, NULL, RDMATransport::event_loop_func, this);
    if (ret) {
        PT_ERROR("pthread_create failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    // fake a self connection request in order to get the shared resources initialized
    request_connection(_vmsg_configuration.local_env_id, ModuleId::P);
    PT_DEBUG("waiting for shared resource allocation");
    sem_wait(&_start_sem);
    PT_DEBUG("wait for shared resource allocation done");

    return VMsgRes::OK;
}

void RDMATransport::stop()
{
    _stop = true;
    pthread_join(_events_thread, NULL);
}

VMsgRes RDMATransport::open_devices()
{
    // Note: this method did not prove itself useful in getting the context of the device on top of soft iwarp
    // need to check if on top of a real device / soft ROcE it will work better

    int n_devices;
    struct ibv_device **device_list = ibv_get_device_list(&n_devices);
    if (!device_list) {
        PT_ERROR("ibv_get_device_list()  failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    PT_DEBUG("num_devices=%d", n_devices);
    for (int i = 0; i < n_devices; ++i) {
        struct ibv_context *ctx = ibv_open_device(device_list[i]);
        if (!ctx) {
            PT_DEBUG("Error, failed to open the device '%s'",
                     ibv_get_device_name(device_list[i]));
            continue;
        }
        const char *dev_name = ibv_get_device_name(ctx->device);

        PT_DEBUG("opened device=%p name='%s'", ctx, dev_name);
        ibv_device_attr attr;
        int ret = ibv_query_device(ctx, &attr);
        if (ret == 0) {
            PT_DEBUG("max_qp=%d max_qp_wr=%d", attr.max_qp, attr.max_qp_wr);
        }
        if (strstr(dev_name, "lo") != NULL) {
            //for now we work with loop back
            PT_DEBUG("using device=%p name='%s'", ctx, dev_name);
            _ibv_ctx = ctx;
        } else {
            PT_DEBUG("closing device='%s'", dev_name);
            ret = ibv_close_device(ctx);
            if (ret) {
                PT_DEBUG("ibv_close_device  failed errno=%d", errno);
            }
        }
    }

    ibv_free_device_list(device_list);
    if (!_ibv_ctx) {
        return VMsgRes::SYS_ERR;
    }
    return VMsgRes::OK;
}

VMsgRes RDMATransport::create_device_resources(ibv_context *ibv_ctx)
{
    _pd = ibv_alloc_pd(ibv_ctx);
    if (!_pd) {
        PT_ERROR("ibv_alloc_pd  failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    PT_DEBUG("created pd %p", _pd);
    _comp_channel = ibv_create_comp_channel(ibv_ctx);
    if (!_comp_channel) {
        PT_ERROR("ibv_create_comp_channel  failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    PT_DEBUG("created channel %p", _comp_channel);

    _cq = ibv_create_cq(ibv_ctx, CQ_DEPTH, this, _comp_channel, 0);
    if (!_cq) {
        PT_ERROR("ibv_create_cq failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    PT_DEBUG("created cq %p", _cq);

    ibv_srq_init_attr srq_attr;
    memset(&srq_attr, 0, sizeof(srq_attr));

    PT_DEBUG("creating SRQs");
    srq_attr.attr.max_sge = 1;
    LOOP(MODULES_COUNT, i) {
        srq_attr.attr.max_wr = _vmsg_configuration.modules[i].num_send_buffers;
        _client_srqs[i] = ibv_create_srq(_pd, &srq_attr);
        if (!_client_srqs[i]) {
            PT_ERROR("ibv_create_srq  failed errno=%d", errno);
            return VMsgRes::SYS_ERR;
        }
        srq_attr.attr.max_wr = _vmsg_configuration.modules[i].num_recv_buffers;
        _server_srqs[i] = ibv_create_srq(_pd, &srq_attr);
        if (!_server_srqs[i]) {
            PT_ERROR("ibv_create_srq  failed errno=%d", errno);
            return VMsgRes::SYS_ERR;
        }
    }
    sem_post(&_start_sem);
    return VMsgRes::OK;
}

void RDMATransport::event_loop()
{
    struct pollfd pfd;
    pfd.fd = _event_channel->fd;
    pfd.events = POLLIN;

    static int POLL_TIMEOUT = 100; // 100 milliseconds
    struct rdma_cm_event *event = NULL;
    while (!_stop) {
        handle_connection_requests();
        int ret = poll(&pfd, 1, POLL_TIMEOUT);
        if (ret == -1) {
            PT_ERROR("poll  failed errno=%d", errno);
            continue;
        }
        if (ret == 0) {
            // poll timeout
            continue;
        }
        // we are only polling this event_channel file descriptor so no need to look at pfd
        ret = rdma_get_cm_event(_event_channel, &event);
        if (ret != 0) {
            PT_ERROR("rdma_get_cm_event  failed errno=%d", errno);
            continue;
        }
        // the event is copied in order to avoid dead locks, more specifically when destroying a cm_id all events
        // related to it must be acked
        struct rdma_cm_event event_copy = *event;
        char private_data_copy[MAX_PRIVATE_DATA];
        if (event->param.conn.private_data_len > 0) {
            memcpy(private_data_copy, event->param.conn.private_data, event->param.conn.private_data_len);
            event_copy.param.conn.private_data = private_data_copy;
        }
        rdma_ack_cm_event(event);
        handle_event(&event_copy);
        PT_DEBUG("waiting for next event");
    }
}

void RDMATransport::on_addr_resolved(struct rdma_cm_event *event)
{
    RDMALink *link = (RDMALink *)event->id->context;
    if (event->status != 0) {
        PT_ERROR("got event error %d", event->status);
        link->set_state(LinkState::ERROR);
        return;
    }

    link->set_state(LinkState::ADDR_RESOLVED);
    int ret = rdma_resolve_route(event->id, RESOLVE_TIMEOUT_MS);
    if (ret) {
        PT_ERROR("rdma_resolve_route failed errno=%d", errno);
        link->set_state(LinkState::ERROR);
    }
}

void RDMATransport::on_route_resolved(struct rdma_cm_event *event)
{
    RDMALink *link = (RDMALink *)event->id->context;
    if (event->status != 0) {
        PT_ERROR("got event error %d", event->status);
        link->set_state(LinkState::ERROR);
        return;
    }
    if (_ibv_ctx == NULL) {
        VMsgRes res = create_device_resources(event->id->verbs);
        ASSERT(res == VMsgRes::OK);
        _ibv_ctx = event->id->verbs;
    }
    link->set_state(LinkState::ROUTE_RESOLVED);
    VMsgRes res = link->establish_connection(_vmsg_configuration.local_env_id, _cq, _pd,
                                             _client_srqs[(uint8_t)link->get_module_id()]);
    if (res == VMsgRes::CONNECTION_REFUSED) {
        PT_WARN("failed to connect to env_id=%u module_id=%hhu, retrying connection",
                link->get_env_id(), link->get_module_id());
        link->reset();
        request_connection(link->get_env_id(), link->get_module_id());
    }
}

void RDMATransport::on_connect_request(struct rdma_cm_event *event)
{
    if (event->status != 0) {
        PT_DEBUG("got event status %d", event->status);
        return;
    }
    if (_ibv_ctx == NULL) {
        // first connection request allocate resources
        VMsgRes res = create_device_resources(event->id->verbs);
        ASSERT(res == VMsgRes::OK);
        _ibv_ctx = event->id->verbs;
    }
    Handshake *handshake = (Handshake *)event->param.conn.private_data;
    ASSERT_EQUAL(event->param.conn.private_data_len, sizeof(Handshake));
    ModuleId module_id = handshake->module_id;
    PT_DEBUG("connect request cm_id=%p dev=%p env_id=%hu module_id=%hhu module_ver=%u vmsg_ver=%u",
             event->id, event->id->verbs, handshake->env_id, module_id, handshake->module_ver, handshake->vmsg_ver);
    RDMALink *srv_link = _server_connections[handshake->env_id][(uint8_t)module_id].get_free_link();
    srv_link->set_state(LinkState::CONNECT_REQUEST);
    srv_link->set_cm_id(event->id);
    srv_link->establish_connection(_vmsg_configuration.local_env_id, _cq, _pd, _server_srqs[(uint8_t)module_id]);
}

void RDMATransport::on_connection_established(struct rdma_cm_event *event)
{
    PT_DEBUG("connection established cm_id=%p", event->id);
    RDMALink *link = (RDMALink *)event->id->context;
    if (link->is_client_link()) {
        Handshake *handshake = (Handshake *)event->param.conn.private_data;
        ASSERT_EQUAL(event->param.conn.private_data_len, sizeof(Handshake));
        ModuleId module_id = handshake->module_id;
        PT_DEBUG("server handshake env_id=%hu module_id=%hhu module_ver=%u vmsg_ver=%u",
                 handshake->env_id, module_id, handshake->module_ver, handshake->vmsg_ver);
        link->set_state(LinkState::CONNECTED);
    }
}

void RDMATransport::handle_event(rdma_cm_event *event)
{
    PT_DEBUG("cma_event type=%s cma_id=%p status=%d", rdma_event_str(event->event), event->id, event->status);

    switch (event->event) {
        case RDMA_CM_EVENT_ADDR_RESOLVED:
            on_addr_resolved(event);
            break;

        case RDMA_CM_EVENT_ROUTE_RESOLVED:
            on_route_resolved(event);
            break;

        case RDMA_CM_EVENT_CONNECT_REQUEST:
            on_connect_request(event);
            break;

        case RDMA_CM_EVENT_ESTABLISHED:
            on_connection_established(event);
            break;

        case RDMA_CM_EVENT_ADDR_ERROR:
        case RDMA_CM_EVENT_ROUTE_ERROR:
        case RDMA_CM_EVENT_CONNECT_ERROR:
        case RDMA_CM_EVENT_UNREACHABLE:
        case RDMA_CM_EVENT_REJECTED:
            PT_ERROR("%s, error %d", rdma_event_str(event->event), event->status);
            break;

        case RDMA_CM_EVENT_DISCONNECTED:
            PT_ERROR("%s id=%p", rdma_event_str(event->event), event->id);
            break;

        case RDMA_CM_EVENT_DEVICE_REMOVAL:
            PT_ERROR("device removal");
            break;

        case RDMA_CM_EVENT_CONNECT_RESPONSE:
        case RDMA_CM_EVENT_MULTICAST_JOIN:
        case RDMA_CM_EVENT_MULTICAST_ERROR:
        case RDMA_CM_EVENT_ADDR_CHANGE:
        case RDMA_CM_EVENT_TIMEWAIT_EXIT:
        default:
            PT_ERROR("unhandled event: %s, ignoring", rdma_event_str(event->event));
            break;
    }
}

VMsgRes RDMATransport::request_connection(EnvId env_id, ModuleId module_id)
{
    ASSERT(env_id < MAX_ENVS);
    ASSERT(module_id < ModuleId::COUNT);

    LockGuard<SpinLock> guard(&_conn_lock);
    ConnectionRequest *request;
    request = _conn_queue.alloc();
    if (request == nullptr) {
        return VMsgRes::NO_RES;
    }
    request->env_id = env_id;
    request->module_id = module_id;
    _conn_queue.push(request);
    return VMsgRes::OK;
}

bool RDMATransport::is_client_connected(EnvId env_id, ModuleId module_id)
{
    RDMALink *link = _client_connections[env_id][(int)module_id].get_next_link();
    return link->get_state() == LinkState::CONNECTED;
}

bool RDMATransport::is_server_connected(EnvId env_id, ModuleId module_id)
{
    RDMALink *link = _server_connections[env_id][(int)module_id].get_next_link();
    return link->get_state() == LinkState::CONNECTED;
}

MemRegion *RDMATransport::register_mem(void *addr, size_t len)
{
    DEBUG_ASSERT(_pd != nullptr);
    struct ibv_mr *mr = ibv_reg_mr(_pd, addr, len, IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE);
    if (mr == NULL) {
        PT_ERROR("ibv_reg_mr  failed errno=%d", errno);
    }
    return (MemRegion *)mr;
}

VMsgRes RDMATransport::unregister_mem(MemRegion *region)
{
    struct ibv_mr *mr = (struct ibv_mr *)region;
    int ret = ibv_dereg_mr(mr);
    if (ret) {
        PT_ERROR("ibv_dereg_mr  failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }
    return VMsgRes::OK;
}

VMsgRes RDMATransport::recv(struct ibv_srq *srq, struct ibv_mr *mr, MsgId msg_id, void *buff, uint32_t len)
{
    struct ibv_sge sg;
    sg.addr = (uintptr_t)buff;
    sg.length = len;
    sg.lkey = mr->lkey;

    struct ibv_recv_wr wr;
    static_assert(sizeof(msg_id) <= sizeof(wr.wr_id), "wr_id should be able to contain msg_id");
    memcpy(&wr.wr_id, &msg_id, sizeof(msg_id));
    wr.sg_list = &sg;
    wr.num_sge = 1;
    wr.next = 0;

    struct ibv_recv_wr *bad_wr;
    if (ibv_post_srq_recv(srq, &wr, &bad_wr)) {
        PT_ERROR("ibv_post_recv failed errno=%d", errno);
        return VMsgRes::SYS_ERR;
    }

    return VMsgRes::OK;
}

VMsgRes RDMATransport::recv_reply(ModuleId module_id, MemRegion *region, MsgId msg_id, void *buff, uint32_t len)
{
    struct ibv_mr *mr = (struct ibv_mr *)region;
    struct ibv_srq *srq = _client_srqs[(uint8_t)module_id];
    return recv(srq, mr, msg_id, buff, len);
}

VMsgRes RDMATransport::recv_request(ModuleId module_id, MemRegion *region, MsgId msg_id, void *buff, uint32_t len)
{
    struct ibv_mr *mr = (struct ibv_mr *)region;
    struct ibv_srq *srq = _server_srqs[(uint8_t)module_id];
    return recv(srq, mr, msg_id, buff, len);
}

VMsgRes RDMATransport::send_request(ModuleGUID module_guid, MemRegion *region, MsgId msg_id, void *buff, uint32_t len)
{
    RDMALink *link = _client_connections[module_guid.env_id][(int)module_guid.module_id].get_next_link();
    struct ibv_mr *mr = (struct ibv_mr *)region;
    return link->send(mr, msg_id, buff, len);
}

VMsgRes RDMATransport::send_response(ModuleGUID module_guid, MemRegion *region, MsgId msg_id, void *buff, uint32_t len)
{
    RDMALink *link = _server_connections[module_guid.env_id][(int)module_guid.module_id].get_next_link();
    struct ibv_mr *mr = (struct ibv_mr *)region;
    return link->send(mr, msg_id, buff, len);
}

static VMsgRes ibv_status_to_vmsg_res(ibv_wc_status status)
{
    switch (status) {
        case IBV_WC_SUCCESS:
            return VMsgRes::OK;
        case IBV_WC_LOC_LEN_ERR:
        case IBV_WC_LOC_QP_OP_ERR:
        case IBV_WC_LOC_EEC_OP_ERR:
        case IBV_WC_LOC_PROT_ERR:
        case IBV_WC_WR_FLUSH_ERR:
        case IBV_WC_MW_BIND_ERR:
        case IBV_WC_BAD_RESP_ERR:
        case IBV_WC_LOC_ACCESS_ERR:
        case IBV_WC_REM_INV_REQ_ERR:
        case IBV_WC_REM_ACCESS_ERR:
        case IBV_WC_REM_OP_ERR:
        case IBV_WC_RETRY_EXC_ERR:
        case IBV_WC_RNR_RETRY_EXC_ERR:
        case IBV_WC_LOC_RDD_VIOL_ERR:
        case IBV_WC_REM_INV_RD_REQ_ERR:
        case IBV_WC_REM_ABORT_ERR:
        case IBV_WC_INV_EECN_ERR:
        case IBV_WC_INV_EEC_STATE_ERR:
        case IBV_WC_FATAL_ERR:
        case IBV_WC_RESP_TIMEOUT_ERR:
        case IBV_WC_GENERAL_ERR:
            return VMsgRes::SYS_ERR;
    }
    PANIC();
}

static TransportEvent::Type ibv_op_code_to_trans_event(ibv_wc_opcode opcode)
{
    switch (opcode) {
        case IBV_WC_SEND:
            return TransportEvent::Type::SEND_COMPLETE;
        case IBV_WC_RDMA_WRITE:
            return TransportEvent::Type::WRITE_COMPLETE;
        case IBV_WC_RDMA_READ:
            return TransportEvent::Type::READ_COMPLETE;
        case IBV_WC_RECV:
            return TransportEvent::Type::MSG_RECV;

        case IBV_WC_COMP_SWAP:
        case IBV_WC_FETCH_ADD:
        case IBV_WC_BIND_MW:
        case IBV_WC_RECV_RDMA_WITH_IMM:
            // currently we are not using these
            PANIC();
    }
    PANIC();
}

int RDMATransport::tpoll(TransportEvent *events, uint32_t max_events)
{
    struct ibv_wc wc_events[MAX_EVENTS_PER_POLL];
    int n_events = ibv_poll_cq(_cq, MIN(NUM_ELEMENTS(wc_events), max_events), wc_events);
    if (n_events < 0) {
        PT_ERROR("ibv_poll_cq failed %d:%s", errno, strerror(errno));
        return -1;
    }

    LOOP(n_events, i) {
        TransportEvent *te = &events[i];
        ibv_wc *we = &wc_events[i];
        memcpy(&te->id, &we->wr_id, sizeof(te->id));

        te->len = we->byte_len;
        if (we->status != IBV_WC_SUCCESS) {
            PT_ERROR("wr_id %lx returned failed status %d:%s",
                     we->wr_id, we->status, ibv_wc_status_str(we->status));
        }
        te->status = ibv_status_to_vmsg_res(we->status);
        te->type = ibv_op_code_to_trans_event(we->opcode);
    }

    return n_events;
}

void RDMATransport::handle_connection_requests()
{
    ConnectionRequest *request;
    _conn_lock.lock();
    request = _conn_queue.pop();
    _conn_lock.unlock();
    if (request == nullptr) {
        return;
    }

    PT_DEBUG("handling connection request to env_id=%hu module_id=%hhu", request->env_id, request->module_id);

    _addr_table->lock();
    EnvAddresses *addresses = _addr_table->get(request->env_id);
    ASSERT(addresses->n_addr > 0, "Env " << request->env_id << " have no addresses configured");
    EnvAddress addr = addresses->addresses[0];
    _addr_table->unlock();

    RDMALink *link = _client_connections[request->env_id][(int)request->module_id].get_free_link();
    link->initiate_connection(_event_channel, addr.host, addr.port);

    _conn_lock.lock();
    _conn_queue.free(request);
    _conn_lock.unlock();
}

}
}
