/* Copyright (C) Vast Data Ltd. */
#include "dev_agent.hpp"

namespace Control {

static const TypeConfig TYPE_CONFIGS[] = {{TypeId::RemoteDevice, sizeof(RemoteDevice), MAX_DEVICES_PER_SYSTEM}};

void DevAgent::init(P::SiloId silo_id, ModuleId module_id, FiberGroupId fiber_group_id)
{
    _db.init(NUM_ELEMENTS(TYPE_CONFIGS), TYPE_CONFIGS);
    _ioprovider.init(MAX_DEVICES_PER_SYSTEM, CONCURRENT_IOS);

    register_server(silo_id, module_id, fiber_group_id);
}

void DevAgent::destroy()
{
    _db.destroy();
    _ioprovider.destroy();
}

void DevAgent::start(FiberGroupId io_provider_fiber_group)
{
    _ioprovider.start(io_provider_fiber_group);
}

void DevAgent::device_add(DeviceAddParams::RootReader *args, P::VProto::Empty::RootBuilder *res)
{
    RemoteDeviceProto::Reader device_reader;
    LOOP(args->get_device_count(), i) {
        args->get_devices(&device_reader, i);
        P::IO::DevIO *devio = _ioprovider.alloc_device(device_reader.get_path(), DEVICE_IO_DEPTH, device_reader.get_size());
        if (devio == nullptr)
            PANIC("Not implemented - should probably go on living and notify control.");

        RemoteDevice *device = _db.create<RemoteDevice>(device_reader.get_guid());
        ASSERT_NOT_NULL(device);

        device->set_devio(devio);
    }
}

void DevAgent::device_remove(DeviceRemoveParams::RootReader *args, P::VProto::Empty::RootBuilder *res)
{
    LOOP(args->get_guid_count(), i) {
        RemoteDevice *device = _db.get<RemoteDevice>(*args->get_guids(i));
        _db.remove(device);
    }
}

void DevAgent::device_prepare_remove(DevicePrepareRemoveParams::RootReader *args, P::VProto::Empty::RootBuilder *res)
{
    LOOP(args->get_guid_count(), i) {
        RemoteDevice *device = _db.get<RemoteDevice>(*args->get_guids(i));
        device->set_alive(false);
    }
}

}
