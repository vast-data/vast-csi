/* Copyright (C) Vast Data Ltd. */
#include "plasma/memory/cpool.hpp"
#include <gtest/gtest.h>
#include "plasma/execution/silo.hpp"
#include "plasma/execution/env.hpp"
#include "test_module.hpp"

#define N_BUFFERS_PER_SILO 100
#define CACHE_SIZE 10

void init_cpool(void *ctx)
{
    uint32_t num_silos = P::Env::get()->get_num_silos();
    P::CPool *pool = (P::CPool *)ctx;
    pool->init(num_silos, CACHE_SIZE, N_BUFFERS_PER_SILO * num_silos, 16);
}

void test_cpool(void *ctx)
{
    P::CPool *pool = (P::CPool *)ctx;

    void *buff[N_BUFFERS_PER_SILO];

    LOOP(N_BUFFERS_PER_SILO, i) {
        buff[i] = pool->alloc(P::Silo::get_current_silo_id());
        ASSERT_NE(buff[i], nullptr);
    }
    LOOP(N_BUFFERS_PER_SILO, i) {
        pool->free_address(P::Silo::get_current_silo_id(), buff[i]);
    }
}

TEST(TestCPool, test)
{
    P::CPool pool;
    TestModule::set_init_func(init_cpool, &pool);
    TestModule::set_start_func(test_cpool, &pool);
    P::Env::get()->run("tests/env_test.config");
    uint32_t num_silos = P::Env::get()->get_num_silos();
    ASSERT_EQ(pool.get_shared_count(), (num_silos * N_BUFFERS_PER_SILO) - (num_silos * CACHE_SIZE));
    pool.destroy(true);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
