/* Copyright (C) Vast Data Ltd. */
#include "os.hpp"
#include <errno.h>
#include <sys/stat.h>
#include "assert.hpp"

namespace P {

void ensure_directory_exists(const char *dir)
{
    int32_t result = mkdir(dir, 0700);
    if (result != 0)
        ASSERT_EQUAL(errno, EEXIST);
}

}
