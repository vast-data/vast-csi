/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "plasma/execution/env.hpp"
#include "globals.hpp"
#include "test_module.hpp"
#include "modules/e_module_agent.rpc.client.hpp"

#define CURRENT_COMPONENT ComponentId::TEST
#define USAGE "\nUsage:\n\ttest_ping <num. of fibers> <num. of pings>\n\n";

using namespace P::VMsg;
using P::Env;
using P::FiberSync::Future;

ModuleAddress dest = {
    0,
    0, //reserved
    (uint8_t) ModuleId::E,
    0,
};

class Guard {
public:
    Guard(uint64_t *sum) { _sum = sum; _start = P::get_time_nano(); };
    ~Guard() { *_sum += P::get_time_nano() - _start; };

    uint64_t *_sum;
    uint64_t _start;
};

typedef struct Context {
    uint64_t n_pings;
    uint64_t n_pings_left;
    uint64_t n_fibers;
    uint64_t total_vmsg_time;
    P::EModuleAgentClient *client;
} Context;

typedef struct FiberContext {
    Future future;
    Context *ctx;
} FiberContext;

static void vmsg_ping(P::EModuleAgentClient *client)
{
    ASSERT(client->vmsg_ping_sync(dest) == VMsgRes::OK);
}

static void fiber_vmsg_ping(void *arg)
{
    FiberContext *fiber_ctx = (FiberContext*)arg;
    Context *ctx = fiber_ctx->ctx;

    while (ctx->n_pings_left > 0)
    {
        ctx->n_pings_left--;
        vmsg_ping(ctx->client);
    }
    fiber_ctx->future.set();
}

static void run_vmsg_ping(void *arg)
{
    Context *ctx = (Context*)arg;
    Future **futures = new Future*[ctx->n_fibers];
    P::EModuleAgentClient client;
    client.init();

    // create backward connection
    vmsg_ping(&client);
    ctx->total_vmsg_time = 0;

    for (int i = 0; i < ctx->n_fibers; i++)
    {
        FiberContext *fiber_ctx = new FiberContext();
        fiber_ctx->future.init();
        futures[i] = &fiber_ctx->future;
        fiber_ctx->ctx = ctx;
        ctx->client = &client;
        P::Fiber::init((P::Index)FiberGroupId::TEST, fiber_vmsg_ping, fiber_ctx, false);
    }
    {
        Guard g1(&ctx->total_vmsg_time);
        Future::wait_all(futures, ctx->n_fibers);
    }
    global_env_stop = true;
}

int main(int argc, char **argv) {
    uint64_t n_fibers;
    uint64_t n_pings;
    switch (argc)
    {
        case 1:
            n_fibers = 1;
            n_pings = 100;
            break;
        case 3:
            n_fibers = atoi(argv[1]);
            n_pings = atoi(argv[2]);
            ASSERT(n_fibers, USAGE);
            ASSERT(n_pings, USAGE);
            break;
        default:
            PANIC(USAGE);
    };

    Context ctx = {
        .n_pings = n_pings,
        .n_pings_left = n_pings,
        .n_fibers = n_fibers,
        .total_vmsg_time = 0,
    };
    TestModule::set_start_func(run_vmsg_ping, &ctx);
    Env::get()->run(argv[0], "tests/test_vmsg_ping.config");

    printf("sent %lu ping packages\ntotal time: %.2lf us.\naverage time: %.2lf ns.\n",
           ctx.n_pings,
           NANO_TO_MICRO((double)ctx.total_vmsg_time),
           (double)ctx.total_vmsg_time/ctx.n_pings);
}
