#/* Copyright (C) Vast Data Ltd. */
#pragma once

#include "modules/i_module_agent.rpc.server.hpp"

class IModule;

class IModuleAgentServerImpl : public IModuleAgentServer {
public:
    void init(P::SiloId silo_id, IModule *module);

private:
    // RPC functions:
    void activate(P::VProto::Empty::RootReader *args, P::VProto::Empty::RootBuilder *result);
    void create_estore(P::VProto::Empty::RootReader *args, P::VProto::Empty::RootBuilder *result);

    IModule *_module;
};
