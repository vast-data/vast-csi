/* Copyright (C) Vast Data Ltd. */
#include <plasma/memory/cpool.hpp>
#include <gtest/gtest.h>
#include <plasma/execution/silo.hpp>
#include <plasma/execution/env.hpp>
#include "test_module.hpp"

#define N_BUFFERS 100

void init_cpool(void *ctx)
{
    P::CPool *pool = (P::CPool *)ctx;
    pool->init(10, N_BUFFERS * P::Env::get()->get_num_silos(), 100);
}

void test_cpool(void *ctx)
{
    P::CPool *pool = (P::CPool *)ctx;

    void *buff[N_BUFFERS];

    LOOP(N_BUFFERS, i) {
        buff[i] = pool->alloc();
        ASSERT_NE(buff[i], nullptr);
    }
    LOOP(N_BUFFERS, i) {
        pool->free(buff[i]);
    }
}

TEST(TestCPool, test)
{
    P::CPool pool;
    test_module_set_init_func(init_cpool, &pool);
    test_module_set_start_func(test_cpool, &pool);
    P::Env::get()->run("tests/env_test.config");
    pool.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
