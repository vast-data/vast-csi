/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <stdio.h>
#include <gtest/gtest.h>
#include <thread>
#include "plasma/execution/env.hpp"
#include "plasma/fiber/sleep.hpp"
#include "globals.hpp"
#include "test_module.hpp"
#include "modules/b_module_agent.rpc.client.hpp"

//#include "test_common_scheduler.hpp"
#define CURRENT_COMPONENT ComponentId::PLASMA

using namespace P::VMsg;
using P::FiberSync::Future;
using P::Env;
using P::SiloId;
using P::Silo;

static void test_lock(void *arg)
{
    TestRpcServerImpl *server = new TestRpcServerImpl();
    server->register_server(silo->get_id(), ModuleId::TEST);




    VMsg *vmsg = P::Env::get()->get_vmsg();

        vmsg->add_module_pair(ModuleId::TEST, ModuleId::B, TransportType::RDMA);
        // vmsg->add_module_pair(ModuleId::B, ModuleId::TEST, TransportType::RDMA);
        /*
        EnvAddresses::RootBuilder addresses;
        addresses.set_n_addr(1);
        strcpy(addresses.get_addresses(0)->get_host(), "127.0.0.1");
        addresses.get_addresses(0)->set_port(4000);
        vmsg->set_env_addresses(0, &addresses);
        */

    PT_ERROR(DATA, "before sleep");
    P::TimerQueues::fast_sleep(1000000);
    PT_ERROR(DATA, "after sleep");

    P::BModuleAgentClient client;
    client.init(P::Env::get()->get_vmsg());

    ModuleGUID dest = {
        0,
        0, //reserved
        (uint8_t) ModuleId::B,
        0,
    };
    
    P::LockParams::RootBuilder *args  = client.alloc_lock();
    args->set_lock_id(666);
    P::VProto::Empty::RootReader *res;
    
    client.lock_sync(dest, args, &res);
    
    P::TimerQueues::fast_sleep(1000000);
    env_stop = true;
}

TEST(TestBox, test)
{
    P::Env *env = P::Env::get();
    // TestModule::set_init_func(init_test_server, nullptr);
    TestModule::set_start_func(test_lock, this);
    std::thread env_thread(&P::Env::run, env, "tests/test_box.config");
    // wait for the env to start
    while (env->get_state() != P::EnvState::RUN) {
        usleep(100);
    }

    usleep(1000000);
    
    // P::Scheduler::init(&scheduler_config);
    
    // P::Fiber::init((P::Index)FiberGroupId::TEST, fiber, nullptr, false);
    
    // P::Scheduler::run();
    // P::Scheduler::run();


    // P::Scheduler::destroy();
    env_stop = true;
    env_thread.join();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
