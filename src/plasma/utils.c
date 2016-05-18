/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <errno.h>
#include <sys/stat.h>

inline bool p_is_power_of_two (uintmax_t x)
{
    return ((x != 0) && ((x & (~x + 1)) == x));
}

void p_ensure_directory_exists(const char *dir)
{
    int32_t result = mkdir(dir, 0700);
    if (result != 0)
        P_ASSERT(errno == EEXIST);
}
