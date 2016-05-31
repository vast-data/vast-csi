/* Copyright (C) Vast Data Ltd. */
#include "p_io_provider.h"

PIOProvider *p_io_provider_init(PDevIO devices[], size_t device_count)
{
    PIOProvider *ioprovider_ret = malloc(sizeof(PIOProvider));
    ioprovider_ret->device_count = device_count;
    ioprovider_ret->devices = devices;

    p_dlistanchor_init(&ioprovider_ret->active_devices_anchor);
    PDListPool *list_pool = p_dlistpool_init((PIndex)device_count);
    p_dlist_init(&ioprovider_ret->active_devices, &ioprovider_ret->active_devices_anchor, list_pool);

    LOOP(device_count, i) {
        p_devio_set_ioprovider(&devices[i], ioprovider_ret);
    }

    return ioprovider_ret;
}

PIOProvider *p_io_provider_init_from_settings(PConfigSetting *io_module)
{
    PConfigSetting* iopool_count_setting = p_config_setting_lookup_required(io_module, "io_pool_count");
    PIndex iopool_count = (PIndex) p_config_setting_get_int32(iopool_count_setting);
    PAtomicPool *iopool = p_atomic_pool_init(iopool_count, sizeof(PIO));

    PConfigSetting *io_provider_setting = p_config_setting_lookup_required(io_module, "io_provider");
    PConfigSetting *devices_setting = p_config_setting_lookup_required(io_provider_setting, "devices");
    const size_t device_count = (size_t)p_config_setting_length(devices_setting);
    PDevIO* devices = malloc(device_count * sizeof(PDevIO));
    LOOP(device_count, i)
    {
        PConfigSetting *device_setting = p_config_setting_get_element(devices_setting, (uint32_t) i);
        PConfigSetting *dev_path_setting = p_config_setting_lookup_required(device_setting, "dev_path");
        PConfigSetting *io_depth_setting = p_config_setting_lookup_required(device_setting, "io_depth");
        PConfigSetting *device_size_setting = p_config_setting_lookup_required(device_setting, "device_size");

        if (unlikely(!p_devio_init(&devices[i], p_config_setting_get_string(dev_path_setting),
                                   (uint32_t)p_config_setting_get_int32(io_depth_setting), iopool,
                                   (size_t)p_config_setting_get_int32(device_size_setting)))) {
            // Todo: this should be replaces with a notification to control and then possibly skip/retry/panic?
            P_PANIC();
        }
    }
    return p_io_provider_init(devices, device_count);
}

void p_io_provider_poll(PIOProvider *io_provider)
{
    P_DLIST_SAFE_EACH(&io_provider->active_devices, index,
        p_devio_poll_events(&io_provider->devices[index]);
    )
}

void p_io_provider_enable_polling(PIOProvider *io_provider, PDevIO *device)
{
    PIndex index = PTR2IDX(device, io_provider->devices);
    p_dlist_append(&io_provider->active_devices, index);
}

void p_io_provider_disable_polling(PIOProvider *io_provider,  PDevIO *device)
{
    PIndex index = PTR2IDX(device, io_provider->devices);
    p_dlist_remove(&io_provider->active_devices, index);
}

void p_io_provider_destroy(PIOProvider *io_provider)
{
    p_dlist_destroy(&io_provider->active_devices);
    LOOP_TYPE(PIndex, io_provider->device_count, index) {
        p_devio_destroy(&io_provider->devices[index]);
    }
}
