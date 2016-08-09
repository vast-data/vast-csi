#include "plasma/trace/emitter.hpp"
#include "plasma/internal.hpp"
#include "plasma/sync/lock_guard.hpp"
#include "plasma/utils/macros.hpp"
#include "address_table.hpp"

using P::Sync::RLockGuard;
using P::Sync::RWSpinLock;

namespace P {
namespace VMsg {

void AddressTable::init()
{
    _lock.init();
    LOOP(MAX_ENVS, i) {
        _addresses[i].n_addr = 0;
    }
}

void AddressTable::destroy()
{
    _lock.destroy();
}

void AddressTable::set(EnvId env_id, EnvAddresses *addresses)
{
    ASSERT(env_id < MAX_ENVS);
    _lock.wlock();
    PT_DEBUG(DATA, "set addresses for env_id=%hu", env_id);
    LOOP(addresses->n_addr, i) {
//        PT_DEBUG(DATA, "addr[%lu] host=%s port=%u", i, addresses->addresses[i].host, addresses->addresses[i].port);
    }
    _addresses[env_id] = *addresses;
    _lock.wunlock();
}

EnvAddresses *AddressTable::get(EnvId env_id)
{
    ASSERT(env_id < MAX_ENVS);
    // verify that the lock is taken
    DEBUG_ASSERT(!_lock.wtrylock());
    return &_addresses[env_id];
}


bool AddressTable::has_addresses(EnvId env_id)
{
    RLockGuard<RWSpinLock> guard(&_lock);
    return _addresses[env_id].n_addr > 0;
}

}
}
