#include "lock_manager_server.hpp"
#include "plasma/execution/env.hpp"


using P::SiloId;
using namespace P::Conf;

namespace LockManager {

void LockManagerServerImpl::init(SiloId silo_id, ModuleId module_id, ConfigSetting *settings)
{
    _size = conf_setting_get_int32(conf_setting_lookup_required(settings, "size"));
    _locks = new P::FiberSync::Qlock[_size];
    LOOP(_size, i)
    {
        _locks[i].init();
    }
    register_server(silo_id, module_id, FiberGroupId::B);
}

void LockManagerServerImpl::lock(LockParams::RootReader *args, P::VProto::Empty::RootBuilder *res)
{
    DEBUG_ASSERT(args->get_lock_id() < _size)
    _locks[args->get_lock_id()].lock();
}

void LockManagerServerImpl::unlock(LockParams::RootReader *args, P::VProto::Empty::RootBuilder *res)
{
    DEBUG_ASSERT(args->get_lock_id() < _size)
    _locks[args->get_lock_id()].unlock();
}

void LockManagerServerImpl::try_lock(LockParams::RootReader *args, TryLockRes::RootBuilder *res)
{
    DEBUG_ASSERT(args->get_lock_id() < _size)
    res->set_success(_locks[args->get_lock_id()].trylock());
}


}  // namespace LockManager
