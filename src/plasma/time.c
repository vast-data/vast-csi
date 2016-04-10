/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <time.h>

uint64_t p_get_clock_time_nano()
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t) ts.tv_sec * 1000000000 + (uint64_t) ts.tv_nsec;
}

static uint64_t rdtscp() {
    uint32_t low, high;
    __asm__ volatile ("rdtscp"
                      : "=a" (low), "=d" (high)
                      :
                      : "%rcx");
    return (uint64_t) low | (((uint64_t) high) << 32);
}

static void native_cpuid(uint32_t *eax, uint32_t *ebx, uint32_t *ecx, uint32_t *edx)
{
    // ecx is often an input as well as an output.
    __asm__ volatile("cpuid"
                     : "=a" (*eax), "=b" (*ebx), "=c" (*ecx), "=d" (*edx)
                     : "0" (*eax), "2" (*ecx));
}

static float get_cycles_per_nano()
{
    uint32_t brand[4 * 3];
    for (size_t i = 0; i < 3; i++) {
        brand[i * 4] = 0x80000002 + (uint32_t) i;
        native_cpuid (&brand[i * 4], &brand[i * 4 + 1], &brand[i * 4 + 2], &brand[i * 4 + 3]);
    }

    // Example string: Intel(R) Core(TM) i7-5557U CPU @ 3.10GHz
    char *freq_string = strstr((char*) brand, "GHz");
    P_ASSERT(freq_string != NULL);

    // Look for the 'GHz' and move the pointer back until space is reached.
    while (*(freq_string - 1) != ' ')
        freq_string--;
    float freq;
    sscanf(freq_string, "%f", &freq);
    return freq;
}

static double nano_per_cycle = 0;
static uint64_t start_nano_secs = 0;

uint64_t p_get_time_nano()
{
    // multiplication is faster than division
    if (start_nano_secs == 0) {
        nano_per_cycle = 1 / get_cycles_per_nano();
        start_nano_secs = p_get_clock_time_nano() - (uint64_t) (rdtscp() * nano_per_cycle);
    }
    return start_nano_secs + (uint64_t) (rdtscp() * nano_per_cycle);
}
