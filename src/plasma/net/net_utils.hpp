#include <cstdint>

#/* Copyright (C) Vast Data Ltd. */

#pragma once

namespace P {
namespace Net {

void bind_socket(int fd, uint16_t port);
int unblock_socket(int fd);


}
}
