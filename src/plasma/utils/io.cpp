#include "plasma/trace/emitter.hpp"
#include "io.hpp"

#define CURRENT_COMPONENT ComponentId::PLASMA
#define CURRENT_CHANNEL DATA

namespace P {
namespace IO {

void IOVecs::trace()
{
    for (uint32_t i = 0; i < count; ++i) {
        PTC_DEBUG("ivoec(%d) iov_base=%p iov_len=%lu", i, iovecs[i].iov_base, iovecs[i].iov_len);
    }
}

}
}
