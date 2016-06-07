#include "test_module.hpp"
#include "plasma/fiber/p_sleep.h"
#include <unistd.h>

using namespace P::Conf;
using P::Silo;

static bool init = false;
static bool started = false;

typedef struct TestModuleState TestModuleState;
struct TestModuleState {
    void *bla;
};

void *test_module_init(Silo *silo, ConfigSetting *setting)
{
    init = true;
    TestModuleState *state = new TestModuleState;
    return state;
}

void test_module_start(void)
{
    started = true;
}

bool test_module_is_init()
{
    return init;
}

bool test_module_is_started()
{
    return started;
}
