/* Copyright (C) Vast Data Ltd. */

/*!
 * \file dev_agent.hpp
 * \brief The device agent. Used by modules that need access to the system's devices.
 */
#pragma once

#include "dev_agent.rpc.server.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/data/ilist.hpp"
#include "control/imdb/component.hpp"
#include "control/imdb/object.hpp"

namespace Control {

static const size_t DEVICE_IO_DEPTH = 64;
static const size_t CONCURRENT_IOS = 65536;
static const size_t MAX_DEVICES_PER_SYSTEM = P::MAX_NVRAMS_PER_SYSTEM + P::MAX_DRIVES_PER_DBOX;

class RemoteDevice : public RemoteObject<TypeId::RemoteDevice> {
public:
    void init()
    {
        RemoteObject<TypeId::RemoteDevice>::init();
        _alive = true;
    }

    void set_devio(P::IO::DevIO *devio) { _devio = devio; }
    P::IO::DevIO *get_devio() { return _devio; }
    void set_alive(bool alive) { _alive = alive; }
    bool get_alive() { return _alive; }

private:
    P::IO::DevIO *_devio;
    bool _alive;
};

class DevAgent : public DevAgentServer {
public:
    void init(P::SiloId silo_id, ModuleId module_id, FiberGroupId fiber_group_id);
    void destroy();
    void start(FiberGroupId io_provider_fiber_group);
    RemoteDevice *get_device(P::GUID guid) { return _db.get<RemoteDevice>(guid); }

    void device_add(DeviceAddParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    void device_remove(DeviceRemoveParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    void device_prepare_remove(DevicePrepareRemoveParams::RootReader *args, P::VProto::Empty::RootBuilder *res);

private:

    IMDB _db;
    P::IO::IOProvider _ioprovider;
};

}
