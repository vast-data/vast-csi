/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_io_provider.h
 * \brief Manages polling over a set of IO devices
 *
 *  Allows polling for IO completions over a set of active devices and wakes IO pending fibers.
 */

#pragma once

#include <p.h>

#include "p_io_provider_private.h"

/*!
 * Initialize a PIOProvider structure.
 * When finished with the PIOProvider call p_io_provider_destroy.
 * \param devices is an array of IO devices to poll when needed.
 * \param device_count is the amount of IO devices passed for this provider.
 */
PIOProvider *p_io_provider_init(PDevIO *devices, size_t device_count);

/*!
 * Initialize a PIOProvider structure according to configuration settings.
 * Note: This instantiate a collection of devices and an IO atomic_pool as well.
 * \param io_module io_module configuration setting - containing iodepth and an array of io_device settings.
 */
PIOProvider *p_io_provider_init_from_settings(PConfigSetting *io_module);

/*!
 * Polls for IO completions on "active" IO devices (those that have pending IOs).
 */
void p_io_provider_poll(PIOProvider *io_provider);

/*!
 * Marks an IO device as active- needs polling for IO completion.
 */
void p_io_provider_enable_polling(PIOProvider *io_provider, PDevIO *device);

/*!
 * Marks an IO device as idle- no polling needed.
 */
void p_io_provider_disable_polling(PIOProvider *io_provider, PDevIO *device);

/*!
 * Release PDevIO structure resources.
 * \param io_provider is the structure to be released.
 */
void p_io_provider_destroy(PIOProvider *io_provider);
