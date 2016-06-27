#include "test_module.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/fiber/fiber.hpp"

using namespace P::Conf;
using P::Silo;

/*static*/ bool TestModule::_init = false;
/*static*/ bool TestModule::_started = false;
/*static*/ TestFunc TestModule::_init_func = nullptr;
/*static*/ void *TestModule::_init_func_ctx = nullptr;
/*static*/ TestFunc TestModule::_start_func = nullptr;
/*static*/ void *TestModule::_start_func_ctx = nullptr;


bool TestModule::is_init()
{
    return _init;
}

bool TestModule::is_started()
{
    return _started;
}

void TestModule::set_init_func(TestFunc func, void *ctx)
{
    _init_func = func;
    _init_func_ctx = ctx;
}

void TestModule::set_start_func(TestFunc func, void *ctx)
{
    _start_func = func;
    _start_func_ctx = ctx;
}

void *TestModule::init(P::Silo *silo, P::Conf::ConfigSetting *setting)
{
    _init = true;
    if (_init_func) {
        _init_func(_init_func_ctx);
    }
    return nullptr;
}

void TestModule::run_start_func()
{
    _start_func(_start_func_ctx);
}

static void start_func_fiber(void *ctx)
{
    printf("test module fiber start\n");
    TestModule::run_start_func();
    printf("test module fiber done\n");

}

void TestModule::start()
{
    _started = true;
    if (_start_func) {
        P::Fiber::init((P::Index)FiberGroupId::TEST, start_func_fiber, nullptr, false);
    }
}
