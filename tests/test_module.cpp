#include "test_module.hpp"
#include "plasma/fiber/p_sleep.h"
#include <unistd.h>

using namespace P::Conf;
using P::Silo;

static bool init = false;
static bool started = false;
static TestFunc init_func = NULL;
static void *init_func_ctx = NULL;
static TestFunc start_func = NULL;
static void *start_func_ctx = NULL;

typedef struct TestModuleState TestModuleState;
struct TestModuleState {
    void *bla;
};

void *test_module_init(Silo *silo, ConfigSetting *setting)
{
    init = true;
    TestModuleState *state = new TestModuleState;
    if (init_func) {
        init_func(init_func_ctx);
    }
    return state;
}

void test_module_start(void)
{
    started = true;
    if (start_func) {
        start_func(start_func_ctx);
    }
}

bool test_module_is_init()
{
    return init;
}

bool test_module_is_started()
{
    return started;
}

void test_module_set_init_func(TestFunc func, void *ctx)
{
    init_func = func;
    init_func_ctx = ctx;
}

void test_module_set_start_func(TestFunc func, void *ctx)
{
    start_func = func;
    start_func_ctx = ctx;
}
