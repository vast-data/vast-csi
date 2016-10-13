/* Copyright (C) Vast Data Ltd. */
/*!
 * \file nfs_utils.hpp
 */

#pragma once

#include "nfs_defs.hpp"
#include "estore/estore.hpp"
#include <cstring>

namespace Nfs {

void nfs_handle_to_ehandle(nfs_fh3 *fh3, EStore::EHandle *handle OUT);
void ehandle_to_nfs_handle(EStore::EHandle handle, nfs_fh3 *fh3 OUT);
void nlm4_lock_to_handle(const nlm4_lock *lock, EStore::EHandle *handle OUT);
void nlm4_lock_to_lock_info(bool exclusive, const nlm4_lock *lock, EStore::LockInfo *lock_info OUT);

}
