/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <stdio.h>
#include <gtest/gtest.h>
#include "plasma/vmsg/vmsg_defs.hpp"
#include "plasma/vmsg/rdma_transport.hpp"

#define CURRENT_COMPONENT ComponentId::PLASMA
#define N_BUFFERS 100

#define BUFF_SIZE (1024 * 1024)
using namespace P::VMsg;

typedef struct TestMsg {
    int  idx;
    char msg[256];
} TestMsg;

TEST(TestRDMATransport, test)
{
    RDMATransport *transport = new RDMATransport();
    AddressTable addr_table;
    addr_table.init();

    EnvAddresses addresses;
    addresses.addresses[0].port = 4000;
    strcpy(addresses.addresses[0].host, "127.0.0.1");
    addresses.n_addr = 1;
    addr_table.set(0, &addresses);

    VMsgConfiguration configuration;
    configuration.local_env_id = 0;
    configuration.modules[(int)ModuleId::TEST].num_recv_buffers = 1024;
    configuration.modules[(int)ModuleId::TEST].num_send_buffers = 1024;
    transport->init(&configuration, &addr_table);
    VMsgRes res = transport->start();
    ASSERT(res == VMsgRes::OK);

    ModuleGUID guid = {0, 0, ModuleId::TEST, 0};
    transport->request_connection(guid.env_id, ModuleId::TEST);
    while (!transport->is_client_connected(guid.env_id, ModuleId::TEST)) {
        usleep(1);
    }
    char *recv_buff = (char *)malloc(BUFF_SIZE);
    memset(recv_buff, 0, BUFF_SIZE);
    char *send_buff = (char *)malloc(BUFF_SIZE);
    memset(send_buff, 0, BUFF_SIZE);

    MemRegion *recv_mr = transport->register_mem(recv_buff, BUFF_SIZE);
    ASSERT(recv_mr != NULL);
    MemRegion *send_mr = transport->register_mem(send_buff, BUFF_SIZE);
    ASSERT(send_mr != NULL);
    int loops = MAX_CONCURRENT_RPC_REQUESTS;
    LOOP_TYPE(uint16_t, loops, i) {
        MsgId rcv_msg_id = {i, 0, 0};
        VMsgRes res = transport->recv_request(guid.module_id, recv_mr, rcv_msg_id,
                                              recv_buff + (i * sizeof(TestMsg)), sizeof(TestMsg));
        ASSERT(res == VMsgRes::OK);
    }

    uint32_t expected_sum = 0;
    LOOP_TYPE(uint16_t, loops, i) {
        TestMsg *msg = (TestMsg *) (send_buff + (sizeof(TestMsg) * i));
        msg->idx = i;
        expected_sum += i;
        snprintf(msg->msg, sizeof(send_buff), "Hello-%d", i);
        MsgId send_msg_id = {i, 1, 0};
        VMsgRes res = transport->send_request(guid, send_mr, send_msg_id,
                                              send_buff + (sizeof(TestMsg) * i), sizeof(TestMsg));
        ASSERT(res == VMsgRes::OK);
    }

    TransportEvent event;
    int rcv_ack = 0;
    uint32_t sum = 0;
    do {
        int n_events = transport->tpoll(&event, 1);
        ASSERT(n_events >= 0);
        if (n_events > 0) {
            TRACE_VMSG_EVENT(event);
            if (event.type == TransportEvent::Type::MSG_RECV) {
                rcv_ack++;
                TestMsg *msg = (TestMsg *) (recv_buff + (event.len * event.id.buffer_index));
                ASSERT(msg->idx == event.id.buffer_index);
                PT_DEBUG("received msg %d '%s'", msg->idx, msg->msg);
                sum += msg->idx;
            } else {
                PANIC();
            }
        } else {
            usleep(1);
        }
    } while (rcv_ack < loops);

    ASSERT(sum == expected_sum);

    transport->unregister_mem(recv_mr);
    transport->unregister_mem(send_mr);

    transport->stop();
    transport->destroy();
    free(recv_buff);
    free(send_buff);
    delete transport;

    printf("Great success !!!\n");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
