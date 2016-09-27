/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "control/cluster/dev_agent.hpp"
#include "plasma/execution/env.hpp"
#include "test_module.hpp"
#include "io_utils.hpp"
#include "globals.hpp"

using namespace Control;
using namespace P;

static int add_count = 0;
static int remove_count = 0;

class Handler : public DevChangeHandler {
public:
    void init(GUID guid)
    {
        DevChangeHandler::init();
        _guid = guid;
    }

    void on_device_addition(RemoteDevice *device)
    {
        EXPECT_TRUE(device->get_alive());
        EXPECT_TRUE(device->get_guid().equals(_guid));
        add_count++;
    }

    void on_device_removal(RemoteDevice *device)
    {
        EXPECT_FALSE(device->get_alive());
        EXPECT_TRUE(device->get_guid().equals(_guid));
        remove_count++;
    }

private:
    GUID _guid;
};

static void init_func(P::Silo *silo, void *ctx)
{
    DevAgent *dev_agent = (DevAgent*) ctx;
    dev_agent->init(silo->get_id(), ModuleId::TEST, FiberGroupId::TEST);
}

static void start_func(void *ctx)
{
    const char *device_path = "/tmp/dev_agent_test.tmp";
    const uint32_t device_size = 4096;
    GUID guid;
    guid.init();

    Test::create_file(device_path, device_size);

    DevAgent *dev_agent = (DevAgent*) ctx;
    Handler h1, h2;
    h1.init(guid);
    h2.init(guid);
    dev_agent->register_handler(&h1);
    dev_agent->register_handler(&h2);

    DeviceAddParams::RootBuilder add_params;
    add_params.init();
    add_params.set_device_count(1);
    add_params.get_devices(0)->set_guid(guid);
    add_params.get_devices(0)->set_size(device_size);
    strcpy(add_params.get_devices(0)->get_path(), device_path);
    dev_agent->device_add(add_params.as_reader(), nullptr);
    ASSERT_EQ(add_count, 2);

    DeviceRemoveParams::RootBuilder remove_params;
    remove_params.init();
    remove_params.set_guid_count(0);
    dev_agent->device_remove(remove_params.as_reader(), nullptr);
    ASSERT_EQ(remove_count, 0);

    remove_params.set_guid_count(1);
    *remove_params.get_guids(0) = guid;
    dev_agent->device_remove(remove_params.as_reader(), nullptr);
    ASSERT_EQ(remove_count, 2);

    env_stop = true;
}

TEST(DevAgent, test)
{
    DevAgent dev_agent;
    TestModule::set_init_func(init_func, &dev_agent);
    TestModule::set_start_func(start_func, &dev_agent);

    env_stop = false;
    P::Env::get()->run("dist/env", "tests/test_dev_agent.config");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
