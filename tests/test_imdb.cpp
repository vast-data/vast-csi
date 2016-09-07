/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "control/imdb/component.hpp"

using namespace P;
using namespace Control;

TEST(TestIMDB, test_guid_hash)
{
    GUID guid;
    guid.init();

    IMDB db;
    db.init();

    ASSERT_EQ(db.get<CNode>(guid), nullptr);
    CNode *c = db.create<CNode>(guid);
    ASSERT_EQ(db.get<CNode>(guid), c);
    db.remove(c);
    ASSERT_EQ(db.get<CNode>(guid), nullptr);
}

TEST(TestIMDB, test_tree)
{
    GUID system_guid, cnode1_guid, cnode2_guid, drive1_guid, drive2_guid;
    system_guid.init();
    cnode1_guid.init();
    cnode2_guid.init();
    drive1_guid.init();
    drive2_guid.init();

    IMDB db;
    db.init();

    System *sys = db.create<System>(system_guid);

    CNode *cnode1 = db.create<CNode>(cnode1_guid);
    cnode1->set_version(1);
    sys->add_child(cnode1);

    CNode *cnode2 = db.create<CNode>(cnode2_guid);
    cnode2->set_version(2);
    sys->add_child(cnode2);

    Drive *drive1 = db.create<Drive>(drive1_guid);
    drive1->set_version(3);
    sys->add_child(drive1);

    Drive *drive2 = db.create<Drive>(drive2_guid);
    drive2->set_version(4);
    sys->add_child(drive2);

    int drive_version_sum = 0;
    int cnode_version_sum = 0;
    CNode *cnode;
    Drive *drive;
    ILIST_ITER_SAFE(sys->get_children(), i) {
        ObjectBase *child = p_container_of(i, ObjectBase, child_node);
        switch (child->get_type_id()) {
        case TypeId::CNode:
            cnode = child->cast<CNode>();
            ASSERT_DEATH(child->cast<Drive>(), "Invalid cast from base type to child.");
            cnode_version_sum += cnode->get_version();
            break;
        case TypeId::Drive:
            drive = child->cast<Drive>();
            ASSERT_DEATH(child->cast<CNode>(), "Invalid cast from base type to child.");
            drive_version_sum += drive->get_version();
            break;
        default:
            break;
        }
        sys->remove_child(child);
        db.remove(child);
    }

    ASSERT_EQ(cnode_version_sum, 3);
    ASSERT_EQ(drive_version_sum, 7);

    int child_count = 0;
    ILIST_ITER(sys->get_children(), i) {
        child_count++;
    }
    ASSERT_EQ(child_count, 0);

    db.remove(sys);
    db.destroy();
}

int main(int argc, char **argv)
{
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
