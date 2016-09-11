#/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/io.hpp"
#include "estore/defs/estore_defs.hpp"
#include "base_block.hpp"

namespace EStore {

struct HandleInfo {
    EHandle handle;
    EAddress ranges_addr;
    SystemAttr attr;
} PACKED;

class HandleBlock : public BaseBlock {
public:
    void init(MIOBuffer *buffer) override;

    void set_handle(EHandle handle);
    EHandle get_handle();
    EAddress get_ranges_addr();
    void set_ranges_addr(EAddress ranges_addr);

    bool is_data_element() { return has_internal_flag(InternalFlags::DATA); }
    bool is_container_element() { return has_internal_flag(InternalFlags::CONTAINER); }

    SystemAttr *get_attr();

private:
    bool has_internal_flag(InternalFlags flag) {
        return (bool)(get_attr()->internal_flags & (uint64_t)flag);
    }
};

}



