/* Copyright (C) Vast Data Ltd. */

/*!
 * \file block_allocator.hpp
 * \brief
 */
#pragma once

namespace Layout {

class BlockAllocator {
    bool alloc(LAddress *addr INOUT);
    void free(const LAddress *addr);
};

}
