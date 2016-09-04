/* Copyright (C) Vast Data Ltd. */

/*!
 * \file block_allocator.hpp
 * \brief
 */
#pragma once

namespace Phys {
namespace Layout {

class BlockAllocator {
    bool alloc(EAddress *eaddr INOUT);
    void free(const EAddress *eaddr);
};

}
}


