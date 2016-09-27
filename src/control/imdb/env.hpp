/* Copyright (C) Vast Data Ltd. */

/*!
 * \file env.hpp
 * \brief Env object implementation.
 */
#pragma once

#include "env.vproto.hpp"
#include "object.hpp"

namespace Control {

class EnvObj : public ControlObject<EnvProto, TypeId::EnvObj> {
public:
    static constexpr char DATA_DIR_PATH[] = "data";

    void generate_config(char *buffer, size_t buf_size);

    bool is_platform();
};

}
