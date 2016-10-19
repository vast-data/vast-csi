#include "io_composer.hpp"

namespace IO {

using IORes::OK;
using P::FiberSync::FutureRes;
using P::IO::IOVec;
using P::IO::IOVecs;
using P::IO::TokenVecs;

WriteBatchToken IOComposer::start_write_batch()
{
    return 0;
}

IORes IOComposer::write(UNUSED WriteBatchToken token, UNUSED DataType data_type, UNUSED FrequencyCategory category,
                        UNUSED IOVecs *io_vecs, UNUSED FutureRes<WriteRes *> result)
{
    // see migrate for flow
    return OK;
}

IORes IOComposer::migrate(UNUSED WriteBatchToken token, UNUSED DataType data_type, UNUSED FrequencyCategory category,
                          UNUSED TokenVecs *addresses, UNUSED FutureRes<WriteRes *> result)
{
    // 1. record the write on the specified batch
    // open a fiber that does the following operations.
    // 2. allocate data buffers, read the data and perform data reduction
    // 3. once data have been reduced aggregate it according to its category.
    //    Note we avoid allocating space on a stripe until we can fill a sub stripe in order to avoid disturbing other
    //    writers making progress on the stripe.
    // 4. once enough data in a specific category have been aggregated to fill a sub stripe (minus raid encoding)
    // 4.1. calculate raid encoding for the sub stripe (might be able to do this while compressing the data?)
    // 4.2 write the sub stripe to flash IO
    // 5. once the stripe owning the write has been fully written (all the sub stripes in the stripe must be written not just our sub stripe)
    //    the write can be marked as committed in the batch.
    return OK;
}

IORes IOComposer::read(UNUSED TokenVecs *addresses, UNUSED IOVecs *io_vecs, UNUSED FutureRes<IORes> *res)
{
    return OK;
}

IORes IOComposer::free(UNUSED TokenVecs *addresses)
{
    return OK;
}

IORes IOComposer::commit_write_batch(UNUSED WriteBatchToken token)
{
    // wait for all writes belonging to the batch to end (the stripe they belong to should be committed)
    return OK;
}

}


