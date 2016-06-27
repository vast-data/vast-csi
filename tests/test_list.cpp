/* Copyright (C) Vast Data Ltd. */

#include "plasma/data/list.hpp"
#include <gtest/gtest.h>

using P::List;
using P::SingleList;

TEST(TestList, test_push)
{
    SingleList single_list;
    single_list.init(3);

    List* list = single_list.list();

    ASSERT_TRUE(list->is_empty());

    list->push(1);
    ASSERT_FALSE(list->is_empty());

    list->push(2);
    EXPECT_EQ(2, list->get_first());

    single_list.destroy();
}

TEST(TestList, test_add_after)
{
    SingleList single_list;
    single_list.init(3);

    List* list = single_list.list();

    list->push(0);
    list->add_after(0, 2);
    list->add_after(0, 1);
    ASSERT_EQ(list->get_first(), 0);
    ASSERT_EQ(list->next(0), 1);
    ASSERT_EQ(list->next(1), 2);
    ASSERT_EQ(list->next(2), P::INVALID_INDEX);
    ASSERT_TRUE(list->is_last(2));

    single_list.destroy();
}

TEST(TestList, test_remove_next)
{
    SingleList single_list;
    single_list.init(3);

    List* list = single_list.list();

    list->push(0);
    list->add_after(0, 1);
    list->add_after(1, 2);
    list->add_after(2, 3);

    list->remove_next(0);
    ASSERT_EQ(list->get_first(), 0);
    ASSERT_EQ(list->next(0), 2);
    ASSERT_EQ(list->next(2), 3);

    list->remove_next(2);
    ASSERT_EQ(list->get_first(), 0);
    ASSERT_EQ(list->next(0), 2);
    ASSERT_TRUE(list->is_last(2));

    single_list.destroy();
}

TEST(TestList, test_each)
{
    SingleList single_list;
    single_list.init(3);

    List* list = single_list.list();

    list->push(0);
    list->add_after(0, 1);
    list->add_after(1, 2);

    int j = 0;
    ITER_EACH(list, i) {
        ASSERT_EQ(i, j++);
    }
    ASSERT_EQ(j, 3);

    j = 0;
    ITER_SAFE_EACH(list, i,
        ASSERT_EQ(i, j++);
        list->pop();
    );
    ASSERT_EQ(j, 3);

    single_list.destroy();
}

TEST(TestList, test_append)
{
    SingleList single_list;
    single_list.init(3);

    List* list = single_list.list();

    list->append(0);
    list->append(1);
    list->append(2);

    ASSERT_EQ(list->get_first(), 0);
    ASSERT_EQ(list->next(0), 1);
    ASSERT_EQ(list->next(1), 2);
    ASSERT_TRUE(list->is_last(2));

    single_list.destroy();
}

TEST(TestList, test_pop)
{
    SingleList single_list;
    single_list.init(3);

    List* list = single_list.list();

    list->append(0);
    list->append(1);
    list->append(2);

    ASSERT_EQ(list->pop(), 0);
    ASSERT_EQ(list->pop(), 1);
    ASSERT_EQ(list->pop(), 2);
    ASSERT_EQ(list->pop(), P::INVALID_INDEX);

    list->append(0);
    list->append(1);
    list->append(2);

    ASSERT_EQ(list->pop(), 0);
    ASSERT_EQ(list->pop(), 1);
    ASSERT_EQ(list->pop(), 2);
    ASSERT_EQ(list->pop(), P::INVALID_INDEX);

    single_list.destroy();
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
