/* Copyright (C) Vast Data Ltd. */
#include "plasma/fiber/sync/future_res.hpp"
#include "plasma/io/devio.hpp"
#include "plasma/io/memio_mock.hpp"
#include "plasma/memory/alloc.hpp"
#include "modules/e_module.hpp"
#include <gtest/gtest.h>

#include "../src/phys/mirrored_io/mio.hpp"
#include "test_common_scheduler.hpp"
#include "test_common_io.hpp"

using namespace P::IO;
using namespace P::FiberSync;
using namespace P::Conf;
using namespace MirroredIO;

const uint64_t test_sectionID = 8;
const Baddr test_baddr = 512;
const WorkerID test_workerID = 888;
const WorkerID other_test_workerID = 999;

// Todo: once a crash testing infrastructure is in place (ORION-64) we should test crashing scenarios here

static void test_locking(void *arg UNUSED)
{
    MirroredAddressToken test_address;
    test_address.token_type = TokenType::MEM;
    test_address.section_id = test_sectionID;
    test_address.byte_offset = 0;

    PhysAddr phys_arr[3];
    LOOP (NUM_ELEMENTS(phys_arr), i) {
        phys_arr[i].dev = new P::IO::MemIOMock();
        phys_arr[i].byte_offset = MemIOMock::mock_address;
    }

    MirroredIOAgent agent;
    agent.init();
    agent.config_section(test_address.section_id, phys_arr, NUM_ELEMENTS(phys_arr), false);
    agent.activate();

    MIO mio;
    mio.init(&agent, 4, 4, 12, FG_C);

    mio.lock(test_address, test_workerID);
    bool got_lock = mio.trylock(test_address, other_test_workerID);
    ASSERT_FALSE(got_lock);
    mio.unlock(test_address, test_workerID);

    got_lock = mio.trylock(test_address, other_test_workerID);
    ASSERT_TRUE(got_lock);
    mio.unlock(test_address, other_test_workerID);
}

TEST(TestMio, test_locking) {
    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, test_locking, nullptr, false);

    P::Scheduler::run();

    P::Scheduler::destroy();
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

static void test_rw(void *arg)
{
    DevIO *test_dev = (DevIO*)arg;

    MirroredAddressToken test_address;
    test_address.token_type = TokenType::NVRAM;
    test_address.section_id = test_sectionID;
    test_address.byte_offset = test_baddr;

    PhysAddr phys_arr[3];
    LOOP (NUM_ELEMENTS(phys_arr), i) {
        phys_arr[i].dev = &test_dev[i];
        phys_arr[i].byte_offset = i * DevIO::O_DIRECT_ALIGNMENT;
    }

    MirroredIOAgent agent;
    agent.init();
    agent.config_section(test_address.section_id, phys_arr, NUM_ELEMENTS(phys_arr), false);
    agent.activate();

    MIO mio;
    mio.init(&agent, 4, 4, 12, FG_C);

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
    ASSERT_EQ(rc, MIO::ReadRet::Success);

    compare_buffers(&read_buff, &write_buff);

    agent.destroy();
}

TEST(TestMio, test_rw) {
    Config* config = conf_init();

    int32_t ret = conf_read_file(config, "tests/test_mio.config");
    ASSERT_TRUE(ret);

    ConfigSetting *io_module = conf_lookup(config, "io_module");

    devices_test_files(io_module, true);

    P::AtomicPool<DevIO::IO> iopool;

    IOProvider io_provider;
    DevIO* test_dev = nullptr;
    P::EModule::init_io_from_settings(io_module, &test_dev, &iopool, &io_provider);

    P::Scheduler::init(&scheduler_config);

    io_provider.start();

    P::Fiber::init(FG_A, test_rw, test_dev, false);

    P::Scheduler::run();

    P::Scheduler::destroy();

    devices_test_files(io_module, false);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
