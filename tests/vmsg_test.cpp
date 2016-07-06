#include "vmsg_test.hpp"

#include <gtest/gtest.h>
#include <unistd.h>
#include <sys/file.h>
#include <sys/mman.h>
#include "plasma/execution/silo.hpp"
#include "plasma/execution/env.hpp"
#include "test_module.hpp"
#include "globals.hpp"
#include "test_module.rpc.server.hpp"
#include "test_module.rpc.client.hpp"

using namespace P::VMsg;
using P::FiberSync::Future;
using P::Env;
using P::SiloId;
using P::Silo;

#define CURRENT_COMPONENT ComponentId::PLASMA

#define TEST_CONFIG_FILE   "tests/vmsg_test.config.in"
#define CLIENT_CONFIG_FILE "tests/vmsg_test_client.config"
#define SERVER_CONFIG_FILE "tests/vmsg_test_server.config"

class TestModuleServerImpl : public TestModuleServer {
public:
    virtual void add(AddArgs *args, uint16_t request_len, AddRes *res, uint16_t *reply_len) override
    {
        ASSERT_EQUAL((size_t)request_len, sizeof(AddArgs));
        res->sum = args->a + args->b;
        PT_DEBUG("%lu + %lu = %lu", args->a, args->b, res->sum);
        *reply_len = sizeof(AddRes);    }

    virtual void multiply(MultiplyArgs *args, uint16_t request_len, MultiplyRes *res, uint16_t *reply_len) override
    {
        ASSERT_EQUAL((size_t)request_len, sizeof(MultiplyArgs));
        res->sum = args->a * args->b * args->c;
        PT_DEBUG("%lu * %lu * %lu = %lu", args->a, args->b, args->c, res->sum);
        *reply_len = sizeof(MultiplyRes);
    }
};

void VMsgTest::init()
{
    srand(time(0));
    debugging = true;
    _lock.init();
    _first_silo = true;
    _finished_silos.store(0);
    init_state();
    create_config_files();
}

void VMsgTest::destroy()
{
    munmap(_state, sizeof(_state));
    if (_client) {
        shm_unlink(SHM_NAME);
    }
}

void VMsgTest::init_state()
{
    _shm_fd = shm_open(SHM_NAME, O_CREAT | O_TRUNC | O_RDWR, 0666);
    ASSERT(_shm_fd >= 0);

    int ret = ftruncate(_shm_fd, sizeof(VMsgTestState));
    ASSERT(ret == 0);

    _state = (VMsgTestState *) mmap(0, sizeof(VMsgTestState), PROT_READ | PROT_WRITE, MAP_SHARED, _shm_fd, 0);
    ASSERT(_state != MAP_FAILED);
    close(_shm_fd);

    _state->_server_shutdown = false;
    _state->_server_shutdown_complete = false;
}

void VMsgTest::do_fork()
{
    _child_pid = fork();
    ASSERT(_child_pid >= 0);
    _client = _child_pid != 0;
}

void VMsgTest::run_test()
{
    do_fork();
    if (_client) {
        run_client();
    } else {
        run_server();
    }
}

void VMsgTest::run_env(const char *config_file)
{
    Env::get()->run(config_file);
}

#define WAIT_LOOPS 10000
#define WAIT_FOR(X, MSG)                                            \
    PT_DEBUG("waiting for %s", MSG);                                \
    LOOP(WAIT_LOOPS, i) {                                           \
        if (X) {                                                    \
            PT_DEBUG("done waiting for %s", MSG);                   \
            break;                                                  \
        }                                                           \
        if (i == WAIT_LOOPS - 1)                                    \
            PANIC("waited too long for " << MSG);                   \
        P::TimerQueues::sleep(P::SleepInterval::SLEEP_100_MILLI);   \
    }


void VMsgTest::add_addresses(EnvId id, uint16_t port)
{
    VMsg *vmsg = Env::get()->get_vmsg();
    _lock.lock();
    if (_first_silo) {
        vmsg->add_module_pair(ModuleId::TEST, ModuleId::TEST, TransportType::RDMA);
        EnvAddresses addresses;
        addresses.n_addr = 1;
        strcpy(addresses.addresses[0].host, "127.0.0.1");
        addresses.addresses[0].port = port;
        vmsg->set_env_addresses(id, &addresses);
        _first_silo = false;
    }
    _lock.unlock();
}

static void finish()
{
    env_stop = true;
}

static void sync_call(TestModuleClient *client, uint64_t i, uint32_t n_silos, EnvId dest_env)
{
    AddArgs *args  = client->alloc_add_args();
    ASSERT_NOT_NULL(args);
    args->a = i;
    args->b = i;

    ModuleGUID dest = {
        dest_env,
        0, //reserved
        (uint8_t) ModuleId::TEST,
        (SiloId)(i % n_silos),
    };

    AddRes *add_res;
    VMsgRes res = client->add_sync(dest, args, &add_res);
    ASSERT(res == VMsgRes::OK);
    ASSERT_EQUAL(args->a + args->b, add_res->sum);
    client->free_add_res(add_res);
}

static void async_call(TestModuleClient *client, uint64_t i, uint32_t n_silos, EnvId dest_env)
{
    static const uint64_t ASYNC_REQUESTS_PER_LOOP = 16;
    VMsgFutureRes<MultiplyRes> *futures[ASYNC_REQUESTS_PER_LOOP];

    ModuleGUID dest = {
        dest_env,
        0, //reserved
        (uint8_t) ModuleId::TEST,
        (P::SiloId)(i % n_silos),
    };

    LOOP(ASYNC_REQUESTS_PER_LOOP, j) {
        MultiplyArgs *margs  = client->alloc_multiply_args();
        ASSERT_NOT_NULL(margs);
        margs->a = i + j;
        margs->b = i - j;
        margs->c = i;

        dest.silo_id = (SiloId)(j % n_silos);
        VMsgRes res = client->multiply_async(dest, margs, &futures[j]);
        ASSERT(res == VMsgRes::OK);
    }
    P::FiberSync::Future::wait_all((P::FiberSync::Future **)futures, ASYNC_REQUESTS_PER_LOOP);
    LOOP(ASYNC_REQUESTS_PER_LOOP, j) {
        ASSERT(futures[j]->is_set());
        MultiplyRes *mul_res = futures[j]->get();
        ASSERT_EQUAL((i + j) * (i - j) * i, mul_res->sum);
        client->free_multiply_res(mul_res);
    }
}

void VMsgTest::client_test()
{
    printf("CLIENT SILO %hhu starting\n", Silo::get_current_silo_id());

    add_addresses(SERVER_ENV_ID, SERVER_PORT);
    uint32_t n_silos = Env::get()->get_num_silos();

    TestModuleClient client;
    client.init(Env::get()->get_vmsg());

    static const uint64_t LOOPS = 1000;
    LOOP(LOOPS, i) {
        sync_call(&client, i, n_silos, SERVER_ENV_ID);
        sync_call(&client, i, n_silos, CLIENT_ENV_ID);
        async_call(&client, i, n_silos, CLIENT_ENV_ID);
        async_call(&client, i, n_silos, SERVER_ENV_ID);

    }
    printf("CLIENT SILO %hhu done\n", Silo::get_current_silo_id());

    if (_finished_silos.fetch_add(1) == (n_silos - 1)) {
        _state->_server_shutdown = true;
        WAIT_FOR(_state->_server_shutdown_complete, "CLIENT: server shutdown complete");
        PT_DEBUG("Exiting CLIENT");
        finish();
    }
}

static TestModuleServerImpl *module_server_init()
{
    TestModuleServerImpl *server = new TestModuleServerImpl();
    server->register_server();
    return server;
}

static void init_test_server(void *)
{
    static TestModuleServer *server = module_server_init();;
}

static void client_test_func(void *ctx)
{
    VMsgTest *test = (VMsgTest *)ctx;
    test->client_test();
}

void VMsgTest::run_client()
{
    TestModule::set_init_func(init_test_server, nullptr);
    TestModule::set_start_func(client_test_func, this);
    run_env(CLIENT_CONFIG_FILE);
}

void VMsgTest::server_test()
{
    add_addresses(CLIENT_ENV_ID, CLIENT_PORT);

    PT_DEBUG("Starting SERVER");
    if (Silo::get_current_silo_id() != 0) {
        PT_DEBUG("SERVER fiber EXIT");
        return;
    }

    WAIT_FOR(_state->_server_shutdown, "SERVER: server shutdown");
    PT_DEBUG("Exiting SERVER");
    _state->_server_shutdown_complete = true;
    finish();
}


static void server_test_func(void *ctx)
{
    VMsgTest *test = (VMsgTest *)ctx;
    test->server_test();
}

void VMsgTest::run_server()
{
    TestModule::set_init_func(init_test_server, nullptr);
    TestModule::set_start_func(server_test_func, this);
    run_env(SERVER_CONFIG_FILE);
}

void VMsgTest::create_config_files()
{
    ASSERT(system("cp " TEST_CONFIG_FILE " " CLIENT_CONFIG_FILE) == 0);
    ASSERT(system("cp " TEST_CONFIG_FILE " " SERVER_CONFIG_FILE) == 0);
    char cmd[256];
    sprintf(cmd, "sed -i 's/{ENV_ID}/%u/g' " CLIENT_CONFIG_FILE, CLIENT_ENV_ID);
    ASSERT(system(cmd) == 0);
    sprintf(cmd, "sed -i 's/{PORT}/%u/g' " CLIENT_CONFIG_FILE, CLIENT_PORT);
    ASSERT(system(cmd) == 0);
    sprintf(cmd, "sed -i 's/{ENV_ID}/%u/g' " SERVER_CONFIG_FILE, SERVER_ENV_ID);
    ASSERT(system(cmd) == 0);
    sprintf(cmd, "sed -i 's/{PORT}/%u/g' " SERVER_CONFIG_FILE, SERVER_PORT);
    ASSERT(system(cmd) == 0);
}

TEST(TestVMsg, test)
{
VMsgTest test;
test.init();
test.run_test();
test.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
