/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include <plasma/memory/cpool.hpp>
#include <gtest/gtest.h>

static PSiloId curr_silo = 0;

extern "C" {

PSiloId __wrap_p_silo_get_id(void);
PSiloId __wrap_p_silo_get_id(void) {
    return curr_silo;
}

}

#define N_BUFFERS 100
#define N_SILOS 4

TEST(TestCPool, test) {
    void *buff[N_BUFFERS];
    P::CPool pool;
    pool.init(N_SILOS, 10, N_BUFFERS, 100);

    curr_silo = 0;
    LOOP(N_BUFFERS, i) {
        buff[i] = pool.alloc();
        ASSERT_NE(buff[i], nullptr);
        curr_silo = (curr_silo + 1) % N_SILOS;
    }
//    pool.print_counters();
    ASSERT_EQ(pool.alloc(), nullptr);
    LOOP(N_BUFFERS, i) {
        pool.free(buff[i]);
        curr_silo = (curr_silo + 1) % N_SILOS;
    }
//    pool.print_counters();
    pool.destroy();
}

int main(int argc, char **argv) {
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
