/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "test.metrics.hpp"
#include "plasma/vmsg/vmsg_defs.hpp"

using namespace P::Metrics;

TEST(TestMetricsParser, test)
{
    Agent agent;
    agent.init();

    NS1::NS2::TestDriveMetrics drive;
    drive.init(&agent, nullptr, "drive");

    auto g = drive.get_generation();
    drive.inc_reads();
    ASSERT_GT(drive.get_generation(), g);

    g = drive.get_generation();
    drive.set_status(123);
    ASSERT_GT(drive.get_generation(), g);

    g = drive.get_generation();
    drive.set_online();
    ASSERT_GT(drive.get_generation(), g);

    drive.dec_reads();
    drive.inc_reads(5);
    drive.dec_reads(5);
    drive.clear_online();

    drive.destroy();
    agent.destroy();
}

TEST(TestMetricsObject, test_clone)
{
    Agent agent;
    agent.init();

    NS1::NS2::TestDriveMetrics parent;
    NS1::NS2::TestDriveMetrics drive;
    drive.init(&agent, &parent, "drive");

    drive.set_reads(1);
    drive.set_writes(2);
    drive.set_status(3);
    drive.set_online(true);

    NS1::NS2::TestDriveMetricsClone clone;
    drive.clone(&clone);
    ASSERT_EQ(&drive, clone.address);
    ASSERT_EQ(clone.parent, &parent);
    ASSERT_EQ(clone.reads, 1);
    ASSERT_EQ(clone.writes, 2);
    ASSERT_EQ(clone.status, 3);
    ASSERT_EQ(clone.online, true);

    drive.destroy();
    agent.destroy();
}

TEST(TestMetricsAgent, test_list)
{
    Agent agent;
    agent.init();

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;
    NS1::NS2::TestDriveMetrics drive3;

    ASSERT_EQ(agent.get_first_object(), nullptr);
    drive1.init(&agent, nullptr, "drive1");
    ASSERT_EQ(agent.get_first_object(), &drive1);
    drive1.destroy();

    drive1.init(&agent, nullptr, "drive1");
    drive2.init(&agent, nullptr, "drive2");
    ASSERT_EQ(agent.get_first_object()->get_next(), &drive2);
    ASSERT_EQ(agent.get_first_object()->get_next()->get_next(), nullptr);

    drive1.destroy();
    ASSERT_EQ(agent.get_first_object(), &drive2);
    ASSERT_EQ(agent.get_first_object()->get_next(), nullptr);
    drive2.destroy();
    ASSERT_EQ(agent.get_first_object(), nullptr);

    drive1.init(&agent, nullptr, "drive1");
    drive2.init(&agent, nullptr, "drive2");
    drive3.init(&agent, nullptr, "drive3");

    drive2.destroy();
    ASSERT_EQ(drive1.get_next(), &drive3);
    drive3.destroy();
    drive1.destroy();
    ASSERT_EQ(agent.get_first_object(), nullptr);
    agent.destroy();
}

TEST(TestMetricsAgent, test_get_generations)
{
    Agent agent;
    agent.init();

    Agent::GetGenerationsParams params;
    Agent::GetGenerationsResult result;
    agent.get_generations(&params, &result);
    ASSERT_EQ(result.update_generation, 0);
    ASSERT_EQ(result.delete_generation, 0);

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;

    drive1.init(&agent, nullptr, "drive1");
    drive2.init(&agent, nullptr, "drive2");

    agent.get_generations(&params, &result);
    ASSERT_EQ(result.update_generation, 2);
    ASSERT_EQ(result.delete_generation, 0);

    drive1.destroy();
    drive2.destroy();

    agent.get_generations(&params, &result);
    ASSERT_EQ(result.update_generation, 2);
    ASSERT_EQ(result.delete_generation, 2);

    agent.destroy();
}

TEST(TestMetricsAgent, test_get_modified)
{
    Agent agent;
    agent.init();

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;

    drive1.init(&agent, nullptr, "drive1");
    drive2.init(&agent, nullptr, "drive2");
    drive1.set_reads(3);
    drive2.set_reads(4);

    // test fetching all objects from the start
    Agent::GetModifiedParams params;
    params.from_object = nullptr;
    params.delete_generation = 666;
    params.from_generation = 0;
    Agent::GetModifiedResult *result = (Agent::GetModifiedResult*) malloc(P::VMsg::RPC_BUFFER_SIZE);
    uint16_t res_len;
    agent.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, false);

    params.delete_generation = 0;
    agent.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->next_object, nullptr);
    ASSERT_EQ(result->count, 2);
    ASSERT_EQ(res_len, sizeof(NS1::NS2::TestDriveMetricsClone) * 2 + sizeof(Agent::GetModifiedResult));

    NS1::NS2::TestDriveMetricsClone *drive1clone = (NS1::NS2::TestDriveMetricsClone*) result->data;
    NS1::NS2::TestDriveMetricsClone *drive2clone = (NS1::NS2::TestDriveMetricsClone*) (result->data + sizeof(NS1::NS2::TestDriveMetricsClone));
    ASSERT_EQ(drive1clone->address, &drive1);
    ASSERT_EQ(drive1clone->reads, 3);
    ASSERT_EQ(drive2clone->reads, 4);

    // test fetching only modified objects
    Agent::GetGenerationsParams gen_params;
    Agent::GetGenerationsResult gen_result;
    agent.get_generations(&gen_params, &gen_result);

    drive2.set_reads(5);
    params.from_generation = gen_result.update_generation;
    agent.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->count, 1);
    drive2clone = (NS1::NS2::TestDriveMetricsClone*) result->data;
    ASSERT_EQ(drive2clone->address, &drive2);

    agent.get_generations(&gen_params, &gen_result);
    params.from_generation = gen_result.update_generation;

    // test fetching the first batch
    NS1::NS2::TestDriveMetrics drives[100];
    LOOP(100, i) {
        drives[i].init(&agent, nullptr, "drive");
        drives[i].set_reads(i);
    }

    int drives_per_msg = 8;
    agent.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->count, drives_per_msg);
    ASSERT_EQ(result->next_object, &drives[drives_per_msg]);

    params.from_object = &drives[drives_per_msg];
    agent.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->count, drives_per_msg);
    ASSERT_EQ(result->next_object, &drives[drives_per_msg * 2]);
    NS1::NS2::TestDriveMetricsClone* driveXclone = (NS1::NS2::TestDriveMetricsClone*) result->data;
    ASSERT_EQ(driveXclone->reads, drives_per_msg);

    drive1.destroy();
    drive2.destroy();
    LOOP(100, i) {
        drives[i].destroy();
    }
    agent.destroy();

    free(result);
}

TEST(TestMetricsAgent, test_get_deletions)
{
    Agent agent;
    agent.init();

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;
    NS1::NS2::TestDriveMetrics drive3;

    drive1.init(&agent, nullptr, "drive1");
    drive2.init(&agent, nullptr, "drive2");
    drive3.init(&agent, nullptr, "drive3");

    Agent::GetDeletionsParams params;
    params.from_generation = 0;
    Agent::GetDeletionsResult *result = (Agent::GetDeletionsResult*) malloc(P::VMsg::RPC_BUFFER_SIZE);
    uint16_t res_len;
    agent.get_deletions(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->has_more, false);
    ASSERT_EQ(result->count, 0);

    drive1.destroy();
    drive2.destroy();
    agent.get_deletions(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->has_more, false);
    ASSERT_EQ(result->count, 2);

    drive3.destroy();
    params.from_generation = 2;
    agent.get_deletions(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->has_more, false);
    ASSERT_EQ(result->count, 1);
    ASSERT_EQ(result->objects[0], &drive3);

    agent.destroy();

    free(result);
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
