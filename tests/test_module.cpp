#include "test_module.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/execution/silo.hpp"
#include "plasma/fiber/fiber.hpp"

using namespace P::Conf;
using P::Silo;

/*static*/ bool TestModule::_init = false;
/*static*/ bool TestModule::_started = false;
/*static*/ InitFunc TestModule::_init_func = nullptr;
/*static*/ void *TestModule::_init_func_ctx = nullptr;
/*static*/ StartFunc TestModule::_start_func = nullptr;
/*static*/ void *TestModule::_start_func_ctx = nullptr;

/* static */ void TestModule::generate_config(P::Conf::ConfigSetting *module_config)
{
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_fiber_group_config(module_config, 10, "TEST");
}

/* static */ void TestModule::get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources)
{
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
}

bool TestModule::is_init()
{
    return _init;
}

bool TestModule::is_started()
{
    return _started;
}

void TestModule::set_init_func(InitFunc func, void *ctx)
{
    _init_func = func;
    _init_func_ctx = ctx;
}

void TestModule::set_start_func(StartFunc func, void *ctx)
{
    _start_func = func;
    _start_func_ctx = ctx;
}

void TestModule::init(P::Silo *silo, UNUSED P::Conf::ConfigSetting *setting)
{
    _init = true;
    if (_init_func) {
        _init_func(silo, _init_func_ctx);
    }
    _agent.init(silo->get_id() , get_id(), FiberGroupId::TEST);
}

void TestModule::run_start_func()
{
    _start_func(_start_func_ctx);
}

static void start_func_fiber(UNUSED void *ctx)
{
    TestModule::run_start_func();

}

void TestModule::start()
{
    _started = true;
    if (_start_func) {
        P::Fiber::init((P::Index)FiberGroupId::TEST, start_func_fiber, nullptr, false);
    }
}
