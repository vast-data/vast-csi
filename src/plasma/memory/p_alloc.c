/* Copyright (C) Vast Data Ltd. */
#include <p.h>

#ifdef __cplusplus
extern "C" {
#endif

void *p_malloc(size_t size)
{
    return malloc(size);
}

void *p_safe_malloc(size_t size)
{
    void *buffer = p_malloc(size);
    P_ASSERT(buffer != NULL);
    return buffer;
}

void *p_cache_aligned_malloc(size_t size)
{
    return aligned_alloc(P_CACHE_LINE_BYTES, size);
}

void *p_safe_cache_aligned_malloc(size_t size)
{
    void *buffer = p_cache_aligned_malloc(size);
    P_ASSERT(buffer != NULL);
    return buffer;
}

void p_fill_zeroes(void *buffer, size_t size)
{
    memset(buffer, 0, size);
}

void p_free(void *buffer)
{
    free(buffer);
}

#ifdef __cplusplus
}
#endif
