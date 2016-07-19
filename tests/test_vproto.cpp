/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "test.vproto.hpp"
#include "test_older.vproto.hpp"

TEST(TestVProto, test_sanity)
{
    const char *name = "foobar";

    NS::Person p;
    p.init();

    strcpy(p.getName(), name);
    p.setAge(120);
    p.setWeight(60);
    p.setActive(true);
    p.setGender(NS::Gender::FEMALE);
    p.setProfession(NS::Profession::PILOT);

    ASSERT_EQ(p.getWeight(), 60);
    ASSERT_EQ(p.getActive(), true);
    ASSERT_EQ(p.getGender(), NS::Gender::FEMALE);
}

TEST(TestVProto, test_init)
{
    uint8_t data[1024];
    LOOP(sizeof(data), i)
        data[i] = 0xff;

    NS::Person *p = new(&data) NS::Person();
    p->init();

    ASSERT_EQ(p->getAge(), 0);
    ASSERT_EQ(p->getActive(), true);
    ASSERT_EQ(p->getProfession(), NS::Profession::PILOT);

    ASSERT_EQ(p->getPhones(1)->getActive(), true);
    ASSERT_EQ(p->getPhones(0)->getActive(), true);
}

TEST(TestVProto, test_array_bounds)
{
    NS::Person p;
    p.init();

    ASSERT_DEATH(p.getPhones(3), "PANIC: assertion failed: \\(index < 2\\) \\(3 < 2\\) Invalid array index at field 'phones' of struct 'Person'");
}

TEST(TestVProto, test_backward_compat)
{
    OldPerson o;
    o.init();
    o.setAge(120);

    NS::Person *p = (NS::Person*) &o;
    // common fields
    ASSERT_EQ(p->getAge(), 120);
    // newer fields
    ASSERT_EQ(p->getName(), nullptr);
    ASSERT_EQ(p->getActive(), true);
    ASSERT_EQ(p->getProfession(), NS::Profession::PILOT);
    // field with no default
    ASSERT_DEATH(p->getWeight(), "PANIC: No default value assigned to field 'weight' of struct 'Person'");
}

int main(int argc, char **argv)
{
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
