/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "plasma/execution/env.hpp"
#include "plasma/fiber/sleep.hpp"
#include "globals.hpp"
#include "test_module.hpp"
#include "lock_manager/lock_manager.rpc.client.hpp"

#define STEP(var) ASSERT_EQUAL(++step, var)
static int step = 0;

using namespace P::VMsg;
using P::Env;

static ModuleAddress dest = {
    0,
    0, //reserved
    (uint8_t) ModuleId::B,
    0,
};

static void lock(LockManager::LockManagerClient *client, size_t lock_id)
{
    LockManager::LockParams::RootBuilder *args;

    args = client->alloc_lock();
    args->set_lock_id(lock_id);
    ASSERT(client->lock_sync(dest, args) == VMsgRes::OK);
}

static void unlock(LockManager::LockManagerClient *client, size_t lock_id)
{
    LockManager::LockParams::RootBuilder *args;

    args = client->alloc_unlock();
    args->set_lock_id(lock_id);
    ASSERT(client->unlock_sync(dest, args) == VMsgRes::OK);
}

static bool try_lock(LockManager::LockManagerClient *client, size_t lock_id)
{
    bool ret;
    LockManager::LockParams::RootBuilder *args;
    RpcGuard<LockManager::TryLockRes::RootReader> res;

    args = client->alloc_try_lock();
    args->set_lock_id(lock_id);
    ASSERT(client->try_lock_sync(dest, args, &res) == VMsgRes::OK);
    ret = res->get_success();
    return ret;
}

static void fiber_lock(void *value)
{
    LockManager::LockManagerClient *client = (LockManager::LockManagerClient *)value;
    STEP(2);
    ASSERT_FALSE(try_lock(client, 10));
    STEP(3);
    lock(client, 10);
    STEP(5);
    unlock(client, 10);
    STEP(6);
}

static void test_lock_manager(UNUSED void *arg)
{
    LockManager::LockManagerClient client;
    client.init();

    // simple tests
    lock(&client, 0);
    lock(&client, 1);
    ASSERT_FALSE(try_lock(&client, 0));
    unlock(&client, 0);
    ASSERT_TRUE(try_lock(&client, 0));

    // double fiber test
    lock(&client, 10);
    STEP(1);
    P::Fiber::init((P::Index)FiberGroupId::TEST, fiber_lock, &client, false);
    P::TimerQueues::fast_sleep(100000);
    STEP(4);
    unlock(&client, 10);
    while (step < 6)
        P::TimerQueues::fast_sleep(1000);

    global_env_stop = true;
}

TEST(TestBox, lock_manager)
{
    TestModule::set_start_func(test_lock_manager, this);
    Env::get()->run("", "tests/test_box.config");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
