/* Copyright (C) Vast Data Ltd. */

#include "plasma/vproto/empty.vproto.hpp"
#include "lock_manager/lock_manager.rpc.client.hpp"
#include "memio.hpp"

namespace P {
namespace IO {

static VMsg::ModuleAddress dest = {
                  0,
                  0, //reserved
                  (uint8_t) ModuleId::B,
                  0,
};

bool MemIO::compare_and_swap(Baddr address, uint64_t new_val, uint64_t exp_val, uint64_t* old_val OUT)
{
    LockManager::CompareAndSwapParams::RootBuilder *args;
    VMsg::RpcGuard<LockManager::CompareAndSwapRes::RootReader> res;
    LockManager::LockManagerClient client;
    client.init();

    args = client.alloc_compare_and_swap();
    args->set_addr(address);
    args->set_new_value(new_val);
    args->set_expected(exp_val);
    VMsg::VMsgRes ret = client.compare_and_swap_sync(dest, args, &res);
    if (ret != VMsg::VMsgRes::OK)
    {
        return false;
    }
    *old_val = res->get_old_value();
    return true;
}

bool MemIO::perform_scattered_io(UNUSED IOVecs buffers[], UNUSED Baddrs *dev_offsets, UNUSED bool is_write, UNUSED Future *io_future)
{
    PANIC("UNIMPLEMENTED!");
    return true;
}

}
}
