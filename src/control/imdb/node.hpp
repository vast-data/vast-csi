/* Copyright (C) Vast Data Ltd. */

/*!
 * \file node.hpp
 * \brief Common functionality to CNodes and DNodes
 */
#pragma once

#include "object.hpp"
#include "env.hpp"
#include "module.hpp"
#include "node.vproto.hpp"

namespace Control {

class BaseNode : public BaseTreeObject {
public:
    EnvObj *get_platform_env()
    {
        return (EnvObj*) get_platform_module()->get_parent();
    }

    PModuleObj *get_platform_module()
    {
        IMDB_ITER_CHILDREN(this, env, EnvObj, {
            PModuleObj *module = env->get_only_child<PModuleObj>();
            if (module != nullptr)
                return module;
        });
        return nullptr;
    }

    virtual BaseNodeProto::Builder *get_node_base() = 0;
};

}
