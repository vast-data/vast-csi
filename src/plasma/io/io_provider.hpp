/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_io_provider.hpp
 * \brief Manages polling over a set of IO devices
 *
 *  Allows polling for IO completions over a set of active devices and wakes IO pending fibers.
 */

#pragma once

#include "../data/dlist.hpp"
#include "devio.hpp"

namespace P {

class DevIO;

class IOProvider {
public:

    DevIO *_devices;

    /*!
     * Initialize a PIOProvider structure.
     * When finished with the PIOProvider call destroy.
     * \param devices is an array of IO devices to poll when needed.
     * \param device_count is the amount of IO devices passed for this provider.
     */
    void init(DevIO *devices, size_t device_count);

    /*!
     * Polls for IO completions on "active" IO devices (those that have pending IOs).
     */
    void poll();

    /*!
     * Marks an IO device as active- needs polling for IO completion.
     */
    void enable_polling(DevIO *device);

    /*!
     * Marks an IO device as idle- no polling needed.
     */
    void disable_polling(DevIO *device);

    /*!
     * Release PDevIO structure resources.
     */
    void destroy();

private:

    // Todo: create a DList holding actual anchor and pool (and not reference)
    DList _active_devices;
    DList::Anchor _active_devices_anchor;
    DList::Pool _active_devices_pool;
    size_t _device_count;
};

};
