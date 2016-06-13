/* Copyright (C) Vast Data Ltd. */

#include <plasma/data/dlist.hpp>
#include <gtest/gtest.h>

using P::DList;

TEST(TestDList, test_insert) {
    DList::Pool list_pool;
    list_pool.init(3);
    DList::Anchor anchor;
    anchor.init();
    DList list;
    list.init(&anchor, &list_pool);

    ASSERT_TRUE(list.is_empty());

    list.insert(1);
    ASSERT_FALSE(list.is_empty());

    list.insert(2);
    ASSERT_EQ(list.get_first(), 2);

    list_pool.destroy();
}

TEST(TestDList, test_add_after) {
    DList::Pool list_pool;
    list_pool.init(3);
    DList::Anchor anchor;
    anchor.init();
    DList list;
    list.init(&anchor, &list_pool);

    list.insert(0);
    list.add_after(0, 2);
    list.add_after(0, 1);
    ASSERT_EQ(list.get_first(), 0);
    ASSERT_EQ(list.next(0), 1);
    ASSERT_EQ(list.next(1), 2);
    ASSERT_EQ(list.next(2), 0);

    list_pool.destroy();
}

TEST(TestDList, test_add_before) {
    DList::Pool list_pool;
    list_pool.init(3);
    DList::Anchor anchor;
    anchor.init();
    DList list;
    list.init(&anchor, &list_pool);

    list.insert(0);
    list.add_before(0, 2);
    list.add_before(0, 1);
    ASSERT_EQ(list.get_first(), 2);
    ASSERT_EQ(list.next(2), 1);
    ASSERT_EQ(list.next(1), 0);
    ASSERT_EQ(list.next(0), 2);

    list_pool.destroy();
}

TEST(TestDList, test_remove) {
    DList::Pool list_pool;
    list_pool.init(3);
    DList::Anchor anchor;
    anchor.init();
    DList list;
    list.init(&anchor, &list_pool);

    list.insert(0);
    list.add_after(0, 1);
    list.add_after(1, 2);

    list.remove(1);
    ASSERT_EQ(list.get_first(), 0);
    ASSERT_EQ(list.next(0), 2);

    list.remove(0);
    ASSERT_EQ(list.get_first(), 2);

    list.remove(2);
    ASSERT_TRUE(list.is_empty());

    list_pool.destroy();
}

TEST(TestDList, test_each) {
    DList::Pool list_pool;
    list_pool.init(3);
    DList::Anchor anchor;
    anchor.init();
    DList list;
    list.init(&anchor, &list_pool);

    list.insert(0);
    list.add_after(0, 1);
    list.add_after(1, 2);

    int j = 0;
    ITER_EACH(&list, i) {
        ASSERT_EQ(i, j++);
    }
    ASSERT_EQ(j, 3);

    j = 0;
    ITER_SAFE_EACH(&list, i,
        ASSERT_EQ(i, j++);
        list.remove(i);
    );
    ASSERT_EQ(j, 3);

    list_pool.destroy();
}

TEST(TestDList, test_queue) {
    DList::Pool list_pool;
    list_pool.init(3);
    DList::Anchor anchor;
    anchor.init();
    DList list;
    list.init(&anchor, &list_pool);

    list.append(0);
    list.append(1);

    ASSERT_EQ(list.pop(), 0);
    ASSERT_EQ(list.pop(), 1);

    list_pool.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
