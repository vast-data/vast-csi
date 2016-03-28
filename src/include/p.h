#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include "plasma/p_assert.h"
#include "plasma/memory/p_alloc.h"
#include "plasma/memory/p_pool.h"
#include "plasma/data/p_dlist.h"

typedef int32_t p_index;
#define P_INVALID_INDEX -1

#define P_CACHE_LINE_BYTES 64
#define P_CACHE_ALIGNED __attribute__ ((aligned(P_CACHE_LINE_BYTES)))
#define P_PACKED __attribute__ ((packed)))
