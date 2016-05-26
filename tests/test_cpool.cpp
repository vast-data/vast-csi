/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <plasma/memory/p_cpool.hpp>

static PSiloId curr_silo = 0;

extern "C" {

PSiloId __wrap_p_silo_get_id(void);
PSiloId __wrap_p_silo_get_id(void) {
    return curr_silo;
}

}

#define N_BUFFERS 100
#define N_SILOS 4

static void test()
{
    void *buff[N_BUFFERS];
    P::CPool pool;
    pool.init(N_SILOS, 10, N_BUFFERS, 100);

    curr_silo = 0;
    LOOP(N_BUFFERS, i) {
        buff[i] = pool.alloc();
        P_ASSERT(buff[i]);
        curr_silo = (curr_silo + 1) % N_SILOS;
    }
//    pool.print_counters();
    P_ASSERT(pool.alloc() == nullptr);
    LOOP(N_BUFFERS, i) {
        pool.free(buff[i]);
        curr_silo = (curr_silo + 1) % N_SILOS;
    }
//    pool.print_counters();
    pool.destroy();
}

int main(void)
{
    test();
}
