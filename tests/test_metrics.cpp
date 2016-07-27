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
    ASSERT_EQ(tracker.get_list()->get_first()->next(), &drive2.list_node);
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
    ASSERT_EQ(drive1.list_node.next(), &drive3.list_node);
    drive3.destroy();
    drive1.destroy();
    ASSERT_TRUE(tracker.get_list()->empty());
    tracker.destroy();
}

TEST(TestMetricsTracker, test_get_generations)
{
    Tracker tracker;
    tracker.init();

    GetGenerationsParams::RootBuilder params;
    GetGenerationsResult::RootBuilder result;
    params.init();
    result.init();

    tracker.get_generations(params.as_reader(), &result);
    auto result_reader = result.as_reader();
    ASSERT_EQ(result_reader->get_update_generation(), 0);
    ASSERT_EQ(result_reader->get_delete_generation(), 0);

    NS1::NS2::TestDriveMetrics drive1;
    NS1::NS2::TestDriveMetrics drive2;

    drive1.init_with_tracker(&tracker, nullptr, "drive1");
    drive2.init_with_tracker(&tracker, nullptr, "drive2");

    tracker.get_generations(params.as_reader(), &result);
    ASSERT_EQ(result_reader->get_update_generation(), 2);
    ASSERT_EQ(result_reader->get_delete_generation(), 0);

    drive1.destroy();
    drive2.destroy();

    tracker.get_generations(params.as_reader(), &result);
    ASSERT_EQ(result_reader->get_update_generation(), 2);
    ASSERT_EQ(result_reader->get_delete_generation(), 2);

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
    GetModifiedParams::RootBuilder params;
    params.init();
    params.set_cookie(0);
    params.set_delete_generation(666);
    params.set_from_generation(0);
    GetModifiedResult::RootBuilder result;
    result.init();
    GetModifiedResult::RootReader *result_reader = result.as_reader();
    uint16_t res_len;
    tracker.get_modified(params.as_reader(), &result, &res_len);
    ASSERT_EQ(result_reader->get_success(), false);

    params.set_delete_generation(0);
    tracker.get_modified(params.as_reader(), &result, &res_len);
    ASSERT_EQ(result_reader->get_success(), true);
    ASSERT_EQ(result_reader->get_cookie(), 0);
    ASSERT_EQ(result_reader->get_count(), 2);

    NS1::NS2::TestDriveMetricsClone *drive1clone = (NS1::NS2::TestDriveMetricsClone*) result_reader->get_data();
    NS1::NS2::TestDriveMetricsClone *drive2clone = (NS1::NS2::TestDriveMetricsClone*) (result_reader->get_data() + sizeof(NS1::NS2::TestDriveMetricsClone));
    ASSERT_EQ(drive1clone->address, &drive1);
    ASSERT_EQ(drive1clone->reads, 3);
    ASSERT_EQ(drive2clone->reads, 4);

    // test fetching only modified objects
    GetGenerationsParams::RootBuilder gen_params;
    GetGenerationsResult::RootBuilder gen_result;
    auto gen_result_reader = gen_result.as_reader();
    gen_params.init();
    gen_result.init();
    tracker.get_generations(gen_params.as_reader(), &gen_result);

    drive2.set_reads(5);
    params.set_from_generation(gen_result_reader->get_update_generation());
    tracker.get_modified(params.as_reader(), &result, &res_len);
    ASSERT_EQ(result_reader->get_success(), true);
    ASSERT_EQ(result_reader->get_count(), 1);
    drive2clone = (NS1::NS2::TestDriveMetricsClone*) result_reader->get_data();
    ASSERT_EQ(drive2clone->address, &drive2);

    tracker.get_generations(gen_params.as_reader(), &gen_result);
    params.set_from_generation(gen_result_reader->get_update_generation());

    // test fetching many objects
    NS1::NS2::TestDriveMetrics drives[100];
    int sum = 0;
    LOOP(100, i) {
        drives[i].init_with_tracker(&tracker, nullptr, "drive");
        drives[i].set_reads(i);
        sum += i;
    }

    int drives_per_msg = result_reader->get_data_count() / sizeof(NS1::NS2::TestDriveMetricsClone);
    NS1::NS2::TestDriveMetricsClone* driveXclone;

    do {
        tracker.get_modified(params.as_reader(), &result, &res_len);
        if (result_reader->get_cookie() != 0)
            ASSERT_EQ(result_reader->get_count(), drives_per_msg);
        ASSERT_EQ(result_reader->get_success(), true);
        LOOP(result_reader->get_count(), i) {
            driveXclone = (NS1::NS2::TestDriveMetricsClone*) (result_reader->get_data() + sizeof(NS1::NS2::TestDriveMetricsClone) * i);
            sum -= driveXclone->reads;
        }
        params.set_cookie(result_reader->get_cookie());
    } while(result_reader->get_cookie() != 0);
    ASSERT_EQ(sum, 0);

    drive1.destroy();
    drive2.destroy();
    LOOP(100, i) {
        drives[i].destroy();
    }
    tracker.destroy();
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

    GetDeletionsParams::RootBuilder params;
    params.init();
    params.set_from_generation(0);
    GetDeletionsResult::RootBuilder result;
    result.init();
    auto result_reader = result.as_reader();
    uint16_t res_len;
    tracker.get_deletions(params.as_reader(), &result, &res_len);
    ASSERT_EQ(result_reader->get_success(), true);
    ASSERT_EQ(result_reader->get_has_more(), false);
    ASSERT_EQ(result_reader->get_count(), 0);

    drive1.destroy();
    drive2.destroy();
    tracker.get_deletions(params.as_reader(), &result, &res_len);
    ASSERT_EQ(result_reader->get_success(), true);
    ASSERT_EQ(result_reader->get_has_more(), false);
    ASSERT_EQ(result_reader->get_count(), 2);

    drive3.destroy();
    params.set_from_generation(2);
    tracker.get_deletions(params.as_reader(), &result, &res_len);
    ASSERT_EQ(result_reader->get_success(), true);
    ASSERT_EQ(result_reader->get_has_more(), false);
    ASSERT_EQ(result_reader->get_count(), 1);
    ASSERT_EQ(*result_reader->get_objects(0), (uint64_t) &drive3);

    tracker.destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
