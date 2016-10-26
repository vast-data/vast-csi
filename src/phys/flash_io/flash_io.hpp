/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <cstdint>
#include "phys/layout/address.hpp"
#include "plasma/fiber/sync/future_res.hpp"
#include "plasma/utils/io.hpp"

namespace IO {

enum class IORes {
    OK,
    IO_ERROR
};

// TODO define struct containing the sub stripe (should correlate with how the IO composer aggregates the writes)
struct SubStripe {

};

struct WriteRes {
    Layout::TokenVecs *token_vecs;
    IORes res;
};
// allocates space from A/R module, waits for R to allow writes to the required stripe
class FlashIO {
public:
    // write a sub stripe
    IORes write_sub_stripe(SubStripe *sub_stripe, P::FiberSync::FutureRes<WriteRes *> result);
    IORes read(Layout::TokenVecs *addresses, P::IO::IOVecs *io_vecs, P::FiberSync::FutureRes<IORes> *res = nullptr);
    IORes free(Layout::TokenVecs *addresses);
};

}

