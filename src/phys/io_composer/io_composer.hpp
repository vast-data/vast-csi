/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <cstdint>
#include "phys/layout/address.hpp"
#include "phys/flash_io/flash_io.hpp"
#include "plasma/fiber/sync/future_res.hpp"
#include "plasma/utils/io.hpp"

// TODO should all IO components share the same namespace and retval
namespace IO {

// type of data, used as a hint for data reduction
enum class DataType {
    USER_DATA,
    META_DATA
};

// frequency in which data is expected to change
enum class FrequencyCategory {
    MINUTE,
    HOUR,
    DAY,
    MONTH
};

typedef uint64_t WriteBatchToken;

// Responsible for composing and aggregating low level io requests from the upper layers
// On the write path, get requests for moving raw data from NVRAM to Flash, orchestrates data reduction, raid encoding
// and writes to flash IO as part of a write batch. Writes are aggregated to sub stripes.
// On the read path, reads reduced (compressed) data, handles degraded reads from flash (raid decoding).
class IOComposer {
public:
    // start a write batch
    WriteBatchToken start_write_batch();

    // write from RAM to flash (to be mainly used for writing metadata)
    IORes write(WriteBatchToken token, DataType data_type, FrequencyCategory category,
                P::IO::IOVecs *io_vecs, P::FiberSync::FutureRes<WriteRes *> result);
    // migrate data from NVRAM to flash as a part of a write batch.
    // the result may be returned once the destination addresses are known and not necessarily once the data have been
    // committed to stable storage. To wait for the data to be committed "commit_write_batch" must be called.
    IORes migrate(WriteBatchToken token, DataType data_type, FrequencyCategory category,
                  Layout::TokenVecs *addresses, P::FiberSync::FutureRes<WriteRes *> result);
    // read from flash, pass a future for an async call
    IORes read(Layout::TokenVecs *addresses, P::IO::IOVecs *io_vecs, P::FiberSync::FutureRes<IORes> *res = nullptr);
    // mark the following addresses as unused
    IORes free(Layout::TokenVecs *addresses);
    // commit the write batch, this method returns only once all the writes belonging to the write batch have been
    // committed to stable storage.
    IORes commit_write_batch(WriteBatchToken token);
};

}
