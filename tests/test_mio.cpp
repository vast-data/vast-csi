/* Copyright (C) Vast Data Ltd. */
#include "globals.hpp"
#include "test_module.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/fiber/sync/future_res.hpp"
#include "plasma/io/devio.hpp"
#include "plasma/io/memio_mock.hpp"
#include "plasma/memory/alloc.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/vmsg/rdma_transport.hpp"
#include "modules/e_module.hpp"
#include "phys/mirrored_io/mio.hpp"
#include "phys/mirrored_io/mio_agent.rpc.client.hpp"
#include <gtest/gtest.h>

#include "test_common_scheduler.hpp"
#include "io_utils.hpp"

using namespace P::IO;
using namespace P::FiberSync;
using namespace P::Conf;
using namespace MirroredIO;
using P::VMsg::RpcGuard;

const uint64_t test_sectionID = 8;
const uint64_t large_sectionID = 9;
const uint64_t unknown_sectionID = 7;
const Baddr test_baddr = 512;
const WorkerID test_workerID = 888;
const WorkerID other_test_workerID = 999;

static const P::VMsg::ModuleAddress dest = {
        0,  // env_id
        0,  // reserved : 4;
        // only the first 4 bits are in use for module ids
        (uint8_t) ModuleId::TEST,  // module_id : 4
        0  // silo_id
};

// Todo: once a crash testing infrastructure is in place (ORION-64) we should test crashing scenarios here

static void init_func(P::Silo *silo, void *ctx)
{
    Control::DevAgent *dev_agent = (Control::DevAgent*) ctx;
    dev_agent->init(silo->get_id(), ModuleId::TEST, FiberGroupId::TEST);
}

static void test_locking_start_func(void *ctx)
{
    MirroredAddressToken test_address;
    test_address.token_type = TokenType::MEM;
    test_address.section_id = test_sectionID;
    test_address.byte_offset = 0;

    PhysAddr phys_arr[3];
    LOOP (NUM_ELEMENTS(phys_arr), i) {
        phys_arr[i].dev = new MemIOMock();
        phys_arr[i].byte_offset = MemIOMock::mock_address;
    }

    Control::DevAgent *dev_agent = (Control::DevAgent*)ctx;

    MIO mio;
    mio.init(0, ModuleId::TEST, (P::Index)FiberGroupId::TEST, dev_agent, 4, 4, 12);

    MirroredIO::MIOAgentClient client;
    client.init();

    mio.get_mio_agent()->config_section(test_address.section_id, phys_arr, NUM_ELEMENTS(phys_arr), false);

    EXPECT_EQ(P::VMsg::VMsgRes::OK, client.activate_sync(dest));

    mio.lock(test_address, test_workerID);
    bool got_lock = mio.trylock(test_address, other_test_workerID);
    ASSERT_FALSE(got_lock);
    mio.unlock(test_address, test_workerID);

    got_lock = mio.trylock(test_address, other_test_workerID);
    ASSERT_TRUE(got_lock);
    mio.unlock(test_address, other_test_workerID);

    env_stop = true;
}

void allocate_test_buffer(IOVec *buff)
{
    buff->iov_base = P::aligned_new_arr<char>(DevIO::O_DIRECT_ALIGNMENT, DevIO::O_DIRECT_ALIGNMENT);
    buff->iov_len = DevIO::O_DIRECT_ALIGNMENT;
}

void fill_test_buffer(char *buff, size_t len)
{
    strncpy(buff, "Avi Nimni is the king!!!", len);
}

static void compare_buffers(IOVec *buff1, IOVec *buff2)
{
    ASSERT_EQ(buff1->iov_len, buff2->iov_len);
    int cmp = strncmp((const char *)buff1->iov_base, (const char *)buff2->iov_base, buff1->iov_len);
    ASSERT_EQ(cmp, 0);
}

static void init_test_data(P::GUID *dev_guids, size_t dev_count, Control::DevAgent *dev_agent)
{
    Control::DeviceAddParams::RootBuilder add_params;
    add_params.init();
    add_params.set_device_count(dev_count);
    constexpr size_t dev_size = 100000;
    for (int i = 0; i < dev_count; ++i) {
        dev_guids[i].init();
        char dev_path[64];
        sprintf(dev_path, "/tmp/io_provider_test_device_file%d.tmp", i);
        add_params.get_devices(i)->set_guid(dev_guids[i]);
        add_params.get_devices(i)->set_size(dev_size);
        strcpy(add_params.get_devices(i)->get_path(), dev_path);
        remove(dev_path);
        Test::create_file(dev_path, dev_size);
    }
    dev_agent->device_add(add_params.as_reader(), nullptr);

    dev_agent->start(FiberGroupId::TEST);
    P::Fiber::yield();  // so that dev_agent will really start.
}

static void test_rw_start_func(void *ctx)
{
    constexpr size_t dev_count = 3;
    constexpr size_t dev_size = 100000;
    P::GUID dev_guids[dev_count];
    Control::DevAgent *dev_agent = (Control::DevAgent*)ctx;
    init_test_data(dev_guids, dev_count, dev_agent);

    MIO mio;
    mio.init(0, ModuleId::TEST, (P::Index)FiberGroupId::TEST, dev_agent, 4, 4, 12);

    MirroredAddressToken test_address;
    test_address.token_type = TokenType::NVRAM;
    test_address.section_id = test_sectionID;
    test_address.byte_offset = test_baddr;

    MirroredIO::MIOAgentClient client;
    client.init();

    ConfigParams::RootBuilder *config_params = client.alloc_config();
    config_params->set_num_sections(1);
    config_params->get_section_configs(0)->set_section_id(test_address.section_id);
    config_params->get_section_configs(0)->set_num_mappings(dev_count);
    config_params->get_section_configs(0)->set_in_rebuild(false);
    for (int i = 0; i < dev_count; ++i) {
        config_params->get_section_configs(0)->get_mappings(i)->set_device_guid(dev_guids[i]);
        config_params->get_section_configs(0)->get_mappings(i)->set_base_offset(i * DevIO::O_DIRECT_ALIGNMENT);
    }
    EXPECT_EQ(P::VMsg::VMsgRes::OK, client.config_sync(dest, config_params));
    EXPECT_EQ(P::VMsg::VMsgRes::OK, client.activate_sync(dest));

    IOVec write_buff;
    allocate_test_buffer(&write_buff);
    fill_test_buffer((char*)write_buff.iov_base, write_buff.iov_len);
    IOVecs write_buffs;
    write_buffs.count = 1;
    write_buffs.iovecs = &write_buff;
    bool written = mio.write(test_address, &write_buffs);
    ASSERT_TRUE(written);

    IOVec read_buff;
    allocate_test_buffer(&read_buff);
    IOVecs read_buffs;
    read_buffs.count = 1;
    read_buffs.iovecs = &read_buff;
    bool was_read = mio.read(test_address, &read_buffs);
    ASSERT_TRUE(was_read);

    compare_buffers(&read_buff, &write_buff);

    FutureRes<bool> commit;
    FutureRes<bool> end;
    commit.init();
    end.init();

    MIO::Buffer protected_wbuff;
    protected_wbuff.init((P::byte*)write_buff.iov_base, write_buff.iov_len);
    fill_test_buffer((char*)protected_wbuff.get_data(), protected_wbuff.get_data_size());

    written = mio.protected_write(test_address, &protected_wbuff, &end, &commit);
    ASSERT_TRUE(written);

    commit.wait();
    ASSERT_TRUE(commit.res);
    end.wait();
    ASSERT_TRUE(end.res);

    MIO::Buffer protected_rbuff;
    protected_rbuff.init((P::byte*)read_buff.iov_base, read_buff.iov_len);
    P::fill_zeroes(read_buff.iov_base, read_buff.iov_len);
    MIO::ReadRet rc = mio.protected_read(test_address, &protected_rbuff, false);
    ASSERT_EQ(rc, MIO::ReadRet::SUCCESS);

    compare_buffers(&read_buff, &write_buff);

    env_stop = true;
}

static void verify_phys_addr_set(MIOAgent::MappingSet *phys_addr_set, PhysAddr *expected_addresses,
                                 P::Index expected_size)
{
    EXPECT_EQ(expected_size, phys_addr_set->size());
    for (P::Index i = 0; i < phys_addr_set->size(); ++i) {
        PhysAddr physical_address;
        phys_addr_set->at(i, &physical_address);
        EXPECT_EQ(expected_addresses[i].dev, physical_address.dev);
        EXPECT_EQ(expected_addresses[i].byte_offset, physical_address.byte_offset);
    }
}

static void test_agent_start_func(void *ctx)
{
    debugging = true;  // EXPECT_DEATH takes a long time - disable the check for starvation.
    P::VMsg::RDMATransport::fork_init();
    constexpr size_t total_dev_count = 5;
    constexpr size_t mapping_dev_count = 3;
    P::GUID dev_guids[total_dev_count];
    Control::DevAgent *dev_agent = (Control::DevAgent*)ctx;
    init_test_data(dev_guids, total_dev_count, dev_agent);
    MIOAgent mio_agent;
    mio_agent.init(0, ModuleId::TEST, (P::Index)FiberGroupId::TEST, dev_agent);

    ConfigParams::RootBuilder config_params;
    config_params.init();
    config_params.set_num_sections(2);
    config_params.get_section_configs(0)->set_section_id(test_sectionID);
    config_params.get_section_configs(0)->set_num_mappings(mapping_dev_count);
    config_params.get_section_configs(0)->set_in_rebuild(false);
    for (int i = 0; i < mapping_dev_count; ++i) {
        config_params.get_section_configs(0)->get_mappings(i)->set_device_guid(dev_guids[i]);
        config_params.get_section_configs(0)->get_mappings(i)->set_base_offset((i + 1) * DevIO::O_DIRECT_ALIGNMENT);
    }
    // Section zero:
    config_params.get_section_configs(1)->set_section_id(0);
    config_params.get_section_configs(1)->set_num_mappings(mapping_dev_count);
    config_params.get_section_configs(1)->set_in_rebuild(false);
    for (int i = 0; i < mapping_dev_count; ++i) {
        config_params.get_section_configs(1)->get_mappings(i)->set_device_guid(dev_guids[i]);
        config_params.get_section_configs(1)->get_mappings(i)->set_base_offset(0);
    }
    mio_agent.config(config_params.as_reader(), nullptr);

    StartRebuildsParams::RootBuilder start_rebuilds_params;
    start_rebuilds_params.init();
    start_rebuilds_params.set_num_section_rebuilds(1);
    SectionRebuildParams::Builder *section_rebuild_params = start_rebuilds_params.get_section_rebuilds(0);
    section_rebuild_params->set_section_id(test_sectionID);
    PhysicalAddress::Builder *new_mapping = section_rebuild_params->get_new_mapping();
    new_mapping->set_device_guid(dev_guids[mapping_dev_count]);
    new_mapping->set_base_offset((mapping_dev_count + 1) * DevIO::O_DIRECT_ALIGNMENT);
    // Rebuild should fail because the agent hasn't been activated yet:
    EXPECT_DEATH(mio_agent.start_rebuilds(start_rebuilds_params.as_reader(), nullptr),
                 "assertion failed: \\(_is_activated\\)");

    mio_agent.activate(nullptr, nullptr);

    MirroredAddressToken section;
    section.token_type = TokenType::NVRAM;
    section.section_id = large_sectionID;
    section.byte_offset = test_baddr;
    MIOAgent::MappingSet phys_addr_set;
    EXPECT_DEATH(mio_agent.start_read(section, &phys_addr_set), "Invalid section ID");
    EXPECT_DEATH(mio_agent.start_write(section, 0 /* write_size */, &phys_addr_set), "Invalid section ID");

    section.section_id = unknown_sectionID;
    PhysAddr expected_addresses[MAX_DEVS_PER_SECTION];
    mio_agent.start_read(section, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, 0);
    mio_agent.done_read(section, &phys_addr_set);

    mio_agent.start_write(section, 0 /* write_size */, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, 0);
    mio_agent.done_write(section, &phys_addr_set);

    section.section_id = test_sectionID;
    for (P::Index i = 0; i < mapping_dev_count; ++i) {
        expected_addresses[i].dev = dynamic_cast<BaseIO*>(dev_agent->get_device(dev_guids[i])->get_devio());
        expected_addresses[i].byte_offset = (i + 1) * DevIO::O_DIRECT_ALIGNMENT + test_baddr;
    }
    mio_agent.start_read(section, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count);
    mio_agent.done_read(section, &phys_addr_set);

    mio_agent.start_write(section, 0 /* write_size */, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count);
    mio_agent.done_write(section, &phys_addr_set);

    RemoveDeviceParams::RootBuilder remove_device_params;
    remove_device_params.init();
    P::GUID unknown_device;
    unknown_device.init();
    remove_device_params.set_device_guid(unknown_device);
    EXPECT_DEATH(mio_agent.remove_device(remove_device_params.as_reader(), nullptr), "Unknown device");

    remove_device_params.set_device_guid(dev_guids[mapping_dev_count]);
    // Removing this device should fail because it's not in section zero:
    EXPECT_DEATH(mio_agent.remove_device(remove_device_params.as_reader(), nullptr),
                 "Device not found in section mappings");

    // Rebuild should fail because this section already has 3 devices:
    EXPECT_DEATH(mio_agent.start_rebuilds(start_rebuilds_params.as_reader(), nullptr),
                 "assertion failed: \\(section_mapping->mapping_data.num_addresses < max_devs_per_section\\)");

    EndRebuildsParams::RootBuilder end_rebuilds_params;
    end_rebuilds_params.init();
    end_rebuilds_params.set_num_section_ids(1);
    *(end_rebuilds_params.get_section_ids(0)) = test_sectionID;
    EXPECT_DEATH(mio_agent.end_rebuilds(end_rebuilds_params.as_reader(), nullptr), "Section is not in rebuild");

    remove_device_params.set_device_guid(dev_guids[1]);
    mio_agent.remove_device(remove_device_params.as_reader(), nullptr);

    for (P::Index i = 0; i < mapping_dev_count - 1; ++i) {
        P::Index dev_idx = i;
        if (dev_idx > 0) {
            ++dev_idx;
        }
        expected_addresses[i].dev = dynamic_cast<BaseIO*>(dev_agent->get_device(dev_guids[dev_idx])->get_devio());
        expected_addresses[i].byte_offset = (dev_idx + 1) * DevIO::O_DIRECT_ALIGNMENT + test_baddr;
    }
    mio_agent.start_read(section, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count - 1);
    mio_agent.done_read(section, &phys_addr_set);

    mio_agent.start_write(section, 0 /* write_size */, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count - 1);
    mio_agent.done_write(section, &phys_addr_set);

    // After removing one device, rebuild should succeed:
    mio_agent.start_rebuilds(start_rebuilds_params.as_reader(), nullptr);

    for (P::Index i = 0; i < mapping_dev_count; ++i) {
        P::Index dev_idx = i;
        if (dev_idx > 0) {
            ++dev_idx;
        }
        expected_addresses[i].dev = dynamic_cast<BaseIO*>(dev_agent->get_device(dev_guids[dev_idx])->get_devio());
        expected_addresses[i].byte_offset = (dev_idx + 1) * DevIO::O_DIRECT_ALIGNMENT + test_baddr;
    }
    mio_agent.start_read(section, &phys_addr_set);
    // During rebuild, the last device (currently being added) shouldn't be read from. Hence, mapping_dev_count - 1:
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count - 1);
    mio_agent.done_read(section, &phys_addr_set);

    mio_agent.start_write(section, 0 /* write_size */, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count);
    mio_agent.done_write(section, &phys_addr_set);

    mio_agent.end_rebuilds(end_rebuilds_params.as_reader(), nullptr);

    mio_agent.start_read(section, &phys_addr_set);
    // After rebuild, the last device is available. Hence, mapping_dev_count:
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count);
    mio_agent.done_read(section, &phys_addr_set);

    mio_agent.start_write(section, 0 /* write_size */, &phys_addr_set);
    verify_phys_addr_set(&phys_addr_set, expected_addresses, mapping_dev_count);
    mio_agent.done_write(section, &phys_addr_set);

    env_stop = true;
}

TEST(TestMio, test_locking) {
    Control::DevAgent dev_agent;
    TestModule::set_init_func(init_func, &dev_agent);
    TestModule::set_start_func(test_locking_start_func, &dev_agent);

    env_stop = false;
    P::Env::get()->run("dist/env", "tests/test_dev_agent.config");
    dev_agent.destroy();
}

TEST(TestMio, test_rw) {
    Control::DevAgent dev_agent;
    TestModule::set_init_func(init_func, &dev_agent);
    TestModule::set_start_func(test_rw_start_func, &dev_agent);

    env_stop = false;
    P::Env::get()->run("dist/env", "tests/test_dev_agent.config");
    dev_agent.destroy();
}

TEST(TestMio, test_agent) {
    Control::DevAgent dev_agent;
    TestModule::set_init_func(init_func, &dev_agent);
    TestModule::set_start_func(test_agent_start_func, &dev_agent);

    env_stop = false;
    P::Env::get()->run("dist/env", "tests/test_dev_agent.config");
    dev_agent.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
