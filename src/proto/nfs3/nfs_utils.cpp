#include <limits>
#include "nfs_utils.hpp"
#include "plasma/trace/emitter.hpp"

#define CURRENT_COMPONENT ComponentId::NFS

using EStore::EHandle;

namespace Nfs {

void nfs_handle_to_ehandle(nfs_fh3 *fh3, EStore::EHandle *handle)
{
    // we are producing the handles so they should be the size of EHandle
    if (fh3->data.data_len != sizeof(EHandle)) {
        PT_WARN(DATA, "invalid handle size=%d", fh3->data.data_len);
        *handle = EStore::INVALID_EHANDLE;
        return;
    }
    *handle = *(EHandle*)fh3->data.data_val;
}

void ehandle_to_nfs_handle(EStore::EHandle handle, nfs_fh3 *fh3 OUT)
{
    fh3->data.data_len = sizeof(EHandle);
    *(EHandle*)fh3->data.data_val = handle;
}

void nlm4_lock_to_handle(const nlm4_lock *lock, EStore::EHandle *handle OUT) {
    const netobj *lock_fh = &lock->fh;
    nfs_fh3 *fh = (nfs_fh3*)(lock_fh->n_bytes);
    nfs_handle_to_ehandle(fh, handle);
}

void nlm4_lock_to_lock_info(bool exclusive, const nlm4_lock *lock, EStore::LockInfo *lock_info OUT) {
    const netobj *owner = &lock->oh;
    lock_info->exclusive = exclusive;
    lock_info->svid = lock->svid;
    lock_info->owner = owner->n_bytes;
    lock_info->owner_len = owner->n_len;
    lock_info->start = lock->l_offset;
    lock_info->end = lock->l_len == 0 ? std::numeric_limits<uint64_t>::max() : lock->l_offset + lock->l_len;
}

}
