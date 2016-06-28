/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>
#include "plasma/sync/rw_spinlock.hpp"
#include "vmsg_defs.hpp"

namespace P {
namespace VMsg {

class AddressTable {
public:
    void init();

    void destroy();

    // set the addresses for the requested env.
    void set(EnvId env_id, EnvAddresses *addresses);

    // get a pointer to the addresses of the requested env, should be done under a lock.
    EnvAddresses *get(EnvId env_id);

    bool has_addresses(EnvId env_id);

    void lock()
    { _lock.rlock(); }

    void unlock()
    { _lock.runlock(); }

public:
    EnvAddresses _addresses[MAX_ENVS];
    P::Sync::RWSpinLock _lock;
};

}
}
