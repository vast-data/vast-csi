/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "test.metrics.hpp"
#include "plasma/vmsg/vmsg_defs.hpp"

using namespace P::Metrics;

TEST(TestMetricsParser, test)
{
    Tracker tracker;
    tracker.init();

    NS1::NS2::TestDriveMetrics drive;
    drive.init_with_tracker(&tracker, nullptr, "drive");

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
    tracker.destroy();
}

TEST(TestMetricsObject, test_clone)
{
    Tracker tracker;
    tracker.init();

    NS1::NS2::TestDriveMetrics parent;
    NS1::NS2::TestDriveMetrics drive;
    drive.init_with_tracker(&tracker, &parent, "drive");

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
    tracker.destroy();
}

TEST(TestMetricsTracker, test_list)
{
    Tracker tracker;
    tracker.init();

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;
    NS1::NS2::TestDriveMetrics drive3;

    ASSERT_TRUE(tracker.get_list()->empty());
    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    ASSERT_EQ(tracker.get_list()->get_first(), &drive1.list_node);
    drive1.destroy();

    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    drive2.init_with_tracker(&tracker, nullptr, "drive2");
    ASSERT_EQ(tracker.get_list()->get_first()->get_next(), &drive2.list_node);
    ASSERT_EQ(tracker.get_list()->get_last(), &drive2.list_node);

    drive1.destroy();
    ASSERT_EQ(tracker.get_list()->get_first(), &drive2.list_node);
    ASSERT_FALSE(tracker.get_list()->empty());
    drive2.destroy();
    ASSERT_TRUE(tracker.get_list()->empty());

    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    drive2.init_with_tracker(&tracker, nullptr, "drive2");
    drive3.init_with_tracker(&tracker, nullptr, "drive3");

    drive2.destroy();
    ASSERT_EQ(drive1.list_node.get_next(), &drive3.list_node);
    drive3.destroy();
    drive1.destroy();
    ASSERT_TRUE(tracker.get_list()->empty());
    tracker.destroy();
}

TEST(TestMetricsTracker, test_get_generations)
{
    Tracker tracker;
    tracker.init();

    Tracker::GetGenerationsParams params;
    Tracker::GetGenerationsResult result;
    tracker.get_generations(&params, &result);
    ASSERT_EQ(result.update_generation, 0);
    ASSERT_EQ(result.delete_generation, 0);

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;

    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    drive2.init_with_tracker(&tracker, nullptr, "drive2");

    tracker.get_generations(&params, &result);
    ASSERT_EQ(result.update_generation, 2);
    ASSERT_EQ(result.delete_generation, 0);

    drive1.destroy();
    drive2.destroy();

    tracker.get_generations(&params, &result);
    ASSERT_EQ(result.update_generation, 2);
    ASSERT_EQ(result.delete_generation, 2);

    tracker.destroy();
}

TEST(TestMetricsTracker, test_get_modified)
{
    Tracker tracker;
    tracker.init();

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;

    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    drive2.init_with_tracker(&tracker, nullptr, "drive2");
    drive1.set_reads(3);
    drive2.set_reads(4);

    // test fetching all objects from the start
    Tracker::GetModifiedParams params;
    params.cookie = nullptr;
    params.delete_generation = 666;
    params.from_generation = 0;
    Tracker::GetModifiedResult *result = (Tracker::GetModifiedResult*) malloc(P::VMsg::RPC_BUFFER_SIZE);
    uint16_t res_len;
    tracker.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, false);

    params.delete_generation = 0;
    tracker.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->cookie, nullptr);
    ASSERT_EQ(result->count, 2);
    ASSERT_EQ(res_len, sizeof(NS1::NS2::TestDriveMetricsClone) * 2 + sizeof(Tracker::GetModifiedResult));

    NS1::NS2::TestDriveMetricsClone *drive1clone = (NS1::NS2::TestDriveMetricsClone*) result->data;
    NS1::NS2::TestDriveMetricsClone *drive2clone = (NS1::NS2::TestDriveMetricsClone*) (result->data + sizeof(NS1::NS2::TestDriveMetricsClone));
    ASSERT_EQ(drive1clone->address, &drive1);
    ASSERT_EQ(drive1clone->reads, 3);
    ASSERT_EQ(drive2clone->reads, 4);

    // test fetching only modified objects
    Tracker::GetGenerationsParams gen_params;
    Tracker::GetGenerationsResult gen_result;
    tracker.get_generations(&gen_params, &gen_result);

    drive2.set_reads(5);
    params.from_generation = gen_result.update_generation;
    tracker.get_modified(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->count, 1);
    drive2clone = (NS1::NS2::TestDriveMetricsClone*) result->data;
    ASSERT_EQ(drive2clone->address, &drive2);

    tracker.get_generations(&gen_params, &gen_result);
    params.from_generation = gen_result.update_generation;

    // test fetching many objects
    NS1::NS2::TestDriveMetrics drives[100];
    int sum = 0;
    LOOP(100, i) {
        drives[i].init_with_tracker(&tracker, nullptr, "drive");
        drives[i].set_reads(i);
        sum += i;
    }

    int drives_per_msg = (P::VMsg::RPC_BUFFER_SIZE - offsetof(Tracker::GetModifiedResult, data)) / sizeof(NS1::NS2::TestDriveMetricsClone);
    NS1::NS2::TestDriveMetricsClone* driveXclone;

    do {
        tracker.get_modified(&params, result, &res_len);
        if (result->cookie != nullptr)
            ASSERT_EQ(result->count, drives_per_msg);
        ASSERT_EQ(result->success, true);
        LOOP(result->count, i) {
            driveXclone = (NS1::NS2::TestDriveMetricsClone*) (result->data + sizeof(NS1::NS2::TestDriveMetricsClone) * i);
            sum -= driveXclone->reads;
        }
        params.cookie = result->cookie;
    } while(result->cookie != nullptr);
    ASSERT_EQ(sum, 0);

    drive1.destroy();
    drive2.destroy();
    LOOP(100, i) {
        drives[i].destroy();
    }
    tracker.destroy();

    free(result);
}

TEST(TestMetricsTracker, test_get_deletions)
{
    Tracker tracker;
    tracker.init();

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;
    NS1::NS2::TestDriveMetrics drive3;

    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    drive2.init_with_tracker(&tracker, nullptr, "drive2");
    drive3.init_with_tracker(&tracker, nullptr, "drive3");

    Tracker::GetDeletionsParams params;
    params.from_generation = 0;
    Tracker::GetDeletionsResult *result = (Tracker::GetDeletionsResult*) malloc(P::VMsg::RPC_BUFFER_SIZE);
    uint16_t res_len;
    tracker.get_deletions(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->has_more, false);
    ASSERT_EQ(result->count, 0);

    drive1.destroy();
    drive2.destroy();
    tracker.get_deletions(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->has_more, false);
    ASSERT_EQ(result->count, 2);

    drive3.destroy();
    params.from_generation = 2;
    tracker.get_deletions(&params, result, &res_len);
    ASSERT_EQ(result->success, true);
    ASSERT_EQ(result->has_more, false);
    ASSERT_EQ(result->count, 1);
    ASSERT_EQ(result->objects[0], &drive3);

    tracker.destroy();

    free(result);
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
