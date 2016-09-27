/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>
#include "control/imdb/component.hpp"
#include "control/imdb/system.hpp"
#include "control/imdb/cnode.hpp"
#include "control/imdb/drive.hpp"

using namespace P;
using namespace Control;

static const TypeConfig TYPE_CONFIGS[] = {{TypeId::CNode, sizeof(CNode), 8},
                                          {TypeId::Drive, sizeof(Drive), 8},
                                          {TypeId::System, sizeof(System), 1}};

TEST(TestIMDB, test_imdb)
{
    GUID guid;
    guid.init();

    IMDB db;
    db.init(NUM_ELEMENTS(TYPE_CONFIGS), TYPE_CONFIGS);

    ASSERT_EQ(db.get<CNode>(guid), nullptr);
    CNode *c = db.create<CNode>(guid);
    ASSERT_EQ(db.get<CNode>(guid), c);
    db.remove(c);
    ASSERT_EQ(db.get<CNode>(guid), nullptr);
}

TEST(TestIMDB, test_get_or_create)
{
    GUID guid;
    guid.init();

    IMDB db;
    db.init(NUM_ELEMENTS(TYPE_CONFIGS), TYPE_CONFIGS);

    CNode *c = db.get_or_create<CNode>(guid, nullptr);

    bool exists;
    ASSERT_EQ(db.get_or_create<CNode>(guid, &exists), c);
    ASSERT_TRUE(exists);

    db.remove(c);
    ASSERT_EQ(db.get_or_create<CNode>(guid, &exists), c);
    ASSERT_FALSE(exists);

    db.remove(c);
    db.destroy();
}

TEST(TestIMDB, test_tree)
{
    TreeDB db;
    db.init(NUM_ELEMENTS(TYPE_CONFIGS), TYPE_CONFIGS);

    System *sys = db.create<System>(GUID::create(), nullptr);

    CNode *cnode1 = db.create<CNode>(GUID::create(), sys);
    cnode1->get_base_node_proto()->set_version(1);
    ASSERT_EQ(cnode1->get_parent(), sys);
    CNode *cnode2 = db.create<CNode>(GUID::create(), sys);
    cnode2->get_base_node_proto()->set_version(2);
    Drive *drive1 = db.create<Drive>(GUID::create(), sys);
    drive1->set_version(3);
    Drive *drive2 = db.create<Drive>(GUID::create(), sys);
    drive2->set_version(4);

    int drive_version_sum = 0;
    int cnode_version_sum = 0;

    IMDB_ITER_CHILDREN(sys, cnode, CNode,
    {
        cnode_version_sum += cnode->get_base_node_proto()->get_version();
    });
    IMDB_ITER_CHILDREN(sys, drive, Drive,
    {
        drive_version_sum += drive->get_version();
    });

    ASSERT_EQ(cnode_version_sum, 3);
    ASSERT_EQ(drive_version_sum, 7);

    CNode *cnode;
    Drive *drive;
    ILIST_ITER_SAFE(sys->get_children(), i) {
        BaseTreeObject *child = p_container_of(i, BaseTreeObject, child_node);
        switch (child->get_type_id()) {
        case TypeId::CNode:
            cnode = child->cast<CNode>();
            ASSERT_DEATH(child->cast<Drive>(), "Invalid cast from base type to child.");
            break;
        case TypeId::Drive:
            drive = child->cast<Drive>();
            ASSERT_DEATH(child->cast<CNode>(), "Invalid cast from base type to child.");
            break;
        default:
            ASSERT_TRUE(0);
            break;
        }
        db.remove(child);
    }

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
