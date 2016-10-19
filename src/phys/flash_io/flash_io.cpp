#include "flash_io.hpp"

namespace IO {

using IORes::OK;
using P::FiberSync::FutureRes;
using P::IO::IOVec;
using P::IO::IOVecs;
using P::IO::TokenVecs;


IORes FlashIO::write_sub_stripe(UNUSED SubStripe *sub_stripe, UNUSED FutureRes<WriteRes *> result)
{
    // 1. allocate a sub stripe from A and return the data the addresses to the caller (by setting the future).
    // 2. write the sub stripe (need to wait per device till the stripe we want to write is the active stripe on that device)
    // Note: waiting per device can probably be done by implementing a network lock in the B-Module, the R-Module will
    // set the active stripe, W-Modules will send an RPC to B that will get stuck until the write is allowed
    // 3. notify A once finished writing a sub stripe.

    return OK;
}

IORes FlashIO::read(UNUSED TokenVecs *addresses, UNUSED IOVecs *io_vecs, UNUSED FutureRes<IORes> *res)
{
    return OK;
}

IORes FlashIO::free(UNUSED TokenVecs *addresses)
{
    return OK;
}

}


