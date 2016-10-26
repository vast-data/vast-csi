/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "phys/layout/section_allocator.rpc.client.hpp"
#include "globals.hpp"
#include "phys/mirrored_io/mio_agent.rpc.client.hpp"
#include "plasma/execution/env.hpp"
#include "estore/io/estore_io.hpp"
#include "plasma/execution/config_internal.hpp"
#include "plasma/io/io_provider.hpp"
#include "modules/e_module.hpp"
#include "plasma/io/devio.hpp"
#include "phys/mirrored_io/mio.hpp"
#include "phys/layout/block_allocator.hpp"
#include "test_common_scheduler.hpp"
#include "test_module.hpp"
#include "io_utils.hpp"


using namespace P::IO;
using namespace P::FiberSync;
using namespace P::Conf;
using namespace MirroredIO;
using namespace EStore;
using namespace Layout;
using P::VMsg::RpcGuard;

static const LAddress head = { .shard_id=0, .addr_type=LAddrType::MD_BLOCKS, .offset=0 };
UNUSED
static const LAddress block_1 = { .shard_id=0, .addr_type=LAddrType::MD_BLOCKS, .offset=1*4*1024 };
static const LAddress block_2 = { .shard_id=0, .addr_type=LAddrType::MD_BLOCKS, .offset=2*4*1024 };
static const P::VMsg::ModuleAddress dest = {
                  0,  // env_id
                  0,  // reserved : 4;
                  // only the first 4 bits are in use for module ids
                  (uint8_t) ModuleId::TEST,  // module_id : 4
                  0  // silo_id
};

static void init_func(P::Silo *silo, void *ctx)
{
    Control::DevAgent *dev_agent = (Control::DevAgent*) ctx;
    dev_agent->init(silo->get_id(), ModuleId::TEST, FiberGroupId::TEST);
}

static void _test_basic(EStore::EStoreIO *estore_io) {
    LAddress addr;
    EStoreRes res;

    res = estore_io->create_block_allocator(LAddrType::MD_BLOCKS);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    res = estore_io->alloc_md_block(0, LAddrType::MD_BLOCKS, &addr);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    res = estore_io->free_md_block(addr);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
}

static void _test_empty_head(EStore::EStoreIO *estore_io) {
    LAddress addr;
    EStoreRes res;
    MIOBuffer buf;
    estore_io->alloc_md_buffers(1, &buf);
    BlocksList *list_block = (BlocksList *)buf.get_data();

    list_block->count = 0;
    list_block->total_count = 1;
    list_block->next = 2;
    res = estore_io->write_md(head, &buf);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    list_block->count = 30;
    list_block->total_count = 0;
    list_block->next = 23;
    list_block->buffers[29] = 1;
    res = estore_io->write_md(block_2, &buf);
    ASSERT_EQ(res, EStore::EStoreRes::OK);

    res = estore_io->alloc_md_block(0, LAddrType::MD_BLOCKS, &addr);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    res = estore_io->read_md(head, &buf, true);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    ASSERT_EQUAL(list_block->count, 30);
    ASSERT_EQUAL(list_block->next, 23);
    ASSERT_EQUAL(addr.shard_id, block_2.shard_id);
    ASSERT_EQUAL(addr.offset, block_2.offset);
}

static void _test_split_head(EStore::EStoreIO *estore_io) {
    EStoreRes res;
    MIOBuffer buf;
    estore_io->alloc_md_buffers(1, &buf);
    BlocksList *list_block = (BlocksList *)buf.get_data();

    list_block->count = NUM_ELEMENTS(list_block->buffers);
    LOOP(list_block->count, i) {
        list_block->buffers[i] = 13;
    }
    list_block->buffers[0] = 11;
    list_block->next = 100;
    res = estore_io->write_md(head, &buf);
    ASSERT_EQ(res, EStore::EStoreRes::OK);

    res = estore_io->free_md_block(block_2);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    res = estore_io->read_md(head, &buf, true);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    ASSERT_EQUAL(list_block->count, 510);
    ASSERT_EQUAL(list_block->next, 2);
    ASSERT_EQUAL(list_block->buffers[0], 11);

    res = estore_io->read_md(block_2, &buf, true);
    ASSERT_EQ(res, EStore::EStoreRes::OK);
    ASSERT_EQUAL(list_block->count, 510);
    ASSERT_EQUAL(list_block->next, 100);
    ASSERT_EQUAL(list_block->buffers[0], 13);
}

static void _test_out_of_memory(EStore::EStoreIO *estore_io) {
    LAddress addr;
    EStoreRes res;
    MIOBuffer buf;
    estore_io->alloc_md_buffers(1, &buf);
    BlocksList *list_block = (BlocksList *)buf.get_data();

    list_block->count = 0;
    list_block->total_count = 10000;
    list_block->next = 0;
    res = estore_io->write_md(head, &buf);
    ASSERT_EQ(res, EStore::EStoreRes::OK);

    res = estore_io->alloc_md_block(0, LAddrType::MD_BLOCKS, &addr);
    ASSERT_EQ(res, EStoreRes::NO_MEM);
}

static void _test_complex(EStore::EStoreIO *estore_io) {
    const int runs = 500;
    const int depth = 20;
    bool alloced_addrs[depth] = {0};
    LAddress addrs[depth];
    EStoreRes res;
    std::srand(std::time(0));

    res = estore_io->create_block_allocator(LAddrType::MD_BLOCKS);
    ASSERT_EQ(res, EStore::EStoreRes::OK);

    LOOP(runs, i) {
        int idx = std::rand() % depth;
        if (alloced_addrs[idx]) {
            res = estore_io->free_md_block(addrs[idx]);
            ASSERT_EQ(res, EStore::EStoreRes::OK);
        }
        else {
            res = estore_io->alloc_md_block(0, LAddrType::MD_BLOCKS, &addrs[idx]);
            ASSERT_EQ(res, EStore::EStoreRes::OK);
        }
        alloced_addrs[idx] = !alloced_addrs[idx];
    }
    LOOP(depth, i) {
        if (alloced_addrs[i]) {
            res = estore_io->free_md_block(addrs[i]);
            ASSERT_EQ(res, EStore::EStoreRes::OK);
        }
    }
}

static void test_block_allocator(void *ctx)
{
    Control::DevAgent *dev_agent = (Control::DevAgent*)ctx;
    EStore::EStoreIO estore_io;
    MIO mio;
    constexpr size_t dev_count = 3;
    constexpr size_t dev_size = 2000000000;
    MirroredIO::MIOAgentClient client;
    Layout::SectionAllocatorClient section_alloc_client;
    P::GUID dev_guids[dev_count];
    Control::DeviceAddParams::RootBuilder add_params;

    add_params.init();
    add_params.set_device_count(dev_count);
    for (size_t i = 0; i < dev_count; ++i) {
        dev_guids[i].init();
        char dev_path[64];
        sprintf(dev_path, "/tmp/io_provider_test_device_file%zu.tmp", i);
        add_params.get_devices(i)->set_guid(dev_guids[i]);
        add_params.get_devices(i)->set_size(dev_size);
        strcpy(add_params.get_devices(i)->get_path(), dev_path);
        remove(dev_path);
        Test::create_file(dev_path, dev_size);
    }

    dev_agent->device_add(add_params.as_reader(), nullptr);
    dev_agent->start(FiberGroupId::TEST);
    P::Fiber::yield();  // so that dev_agent will really start.

    mio.init(0, ModuleId::TEST, (P::Index)FiberGroupId::TEST, dev_agent, 4, 4, 12);
    estore_io.init(0, ModuleId::TEST, FiberGroupId::TEST, &mio);

    {
        client.init();
        ConfigParams::RootBuilder *config_params = client.alloc_config();
        config_params->set_num_sections(1);
        config_params->get_section_configs(0)->set_section_id(1);
        config_params->get_section_configs(0)->set_num_mappings(dev_count);
        config_params->get_section_configs(0)->set_in_rebuild(false);
        for (size_t i = 0; i < dev_count; ++i) {
            config_params->get_section_configs(0)->get_mappings(i)->set_device_guid(dev_guids[i]);
            config_params->get_section_configs(0)->get_mappings(i)->set_base_offset(i * DevIO::O_DIRECT_ALIGNMENT);
        }
        EXPECT_EQ(P::VMsg::VMsgRes::OK, client.config_sync(dest, config_params));
        EXPECT_EQ(P::VMsg::VMsgRes::OK, client.activate_sync(dest));
    }

    {
        section_alloc_client.init();
        SectionAllocatorActivateParams::RootBuilder *activate_config = section_alloc_client.alloc_activate();
        activate_config->set_estore_shard_count(2);
        activate_config->set_max_section_id(2);
        section_alloc_client.activate_sync(dest, activate_config);
    }

    _test_basic(&estore_io);
    _test_empty_head(&estore_io);
    _test_split_head(&estore_io);
    _test_out_of_memory(&estore_io);
    _test_complex(&estore_io);

    global_env_stop = true;
}

TEST(TestMio, test_block_allocator) {
    Control::DevAgent dev_agent;
    TestModule::set_init_func(init_func, &dev_agent);
    TestModule::set_start_func(test_block_allocator, &dev_agent);

    global_env_stop = false;
    P::Env::get()->run("dist/env", "tests/test_block_allocator.config");
    dev_agent.destroy();
}

int main(int argc, char **argv) {
    global_test_mode = true;
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
