#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>

namespace P {
namespace VMsg {

enum class RpcServerId: uint8_t {
    TestRpc,
    MetricsAgent,
    PModuleAgent,
    BModuleAgent,
    EModuleAgent,
    LockManager,
    Cluster,

    COUNT
};

class RpcServer {
public:
    virtual RpcServerId get_server_id() = 0;
    virtual FiberGroupId get_op_fiber_group(uint8_t op_id) = 0;
    virtual void run_op(uint8_t op_id, void *request, uint16_t request_len, void *reply, uint16_t *reply_len) = 0;
};

}
}
