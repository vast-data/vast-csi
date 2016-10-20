/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "lock_manager/lock_manager.vproto.hpp"
#include "lock_manager/lock_manager.rpc.server.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/fiber/sync/qlock.hpp"

namespace LockManager {

class LockManagerServerImpl : public LockManagerServer {
public:
    void init(P::SiloId silo_id, ModuleId module_id, P::Conf::ConfigSetting *settings);

private:
    void lock(LockParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    void unlock(LockParams::RootReader *args, P::VProto::Empty::RootBuilder *res);
    void try_lock(LockParams::RootReader *args, TryLockRes::RootBuilder *res);
    void compare_and_swap(CompareAndSwapParams::RootReader *args, CompareAndSwapRes::RootBuilder *res);

    size_t _size;
    uint64_t *_owners;
    P::FiberSync::Qlock *_locks;
};  // class LockManagerServerImpl

}  // namespace LockManager
