#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>

namespace P {
namespace VMsg {

class ModuleServer {
public:
    virtual ModuleId get_module_id() = 0;
    virtual FiberGroupId get_op_fiber_group(uint16_t op_id) = 0;
    virtual void run_op(uint16_t op_id, void *request, uint16_t request_len, void *reply, uint16_t *reply_len) = 0;
};

}
}