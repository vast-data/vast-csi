/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "test.vproto.hpp"
#include "test_older.vproto.hpp"

// this following includes exist purely to make sure the code compiles
#include "test_import.vproto.hpp"
#include "plasma/vproto/empty.vproto.hpp"

TEST(TestVProto, test_sanity)
{
    const char *name = "foobar";
    const char *street = "elm";

    NS::Person::RootBuilder person_builder;
    person_builder.init();

    strcpy(person_builder.get_name(), name);
    person_builder.set_age(120);
    person_builder.set_weight(60);
    person_builder.set_active(true);
    person_builder.set_gender(NS::Gender::FEMALE);
    person_builder.set_profession(NS::Profession::PILOT);
    ASSERT_EQ(person_builder.get_age(), 120);

    NS::Phone::Builder *phone_builder = person_builder.get_phones(0);
    phone_builder->set_number(144);
    phone_builder = person_builder.get_phones(1);
    phone_builder->set_number(143);

    NS::Address::Builder *address_builder = person_builder.get_address();
    address_builder->set_number(12);
    strcpy(address_builder->get_street(), street);

    phone_builder = person_builder.get_phones(1);
    phone_builder->set_number(143);

    NS::Person::RootReader *person_reader = person_builder.as_reader();
    ASSERT_STREQ(person_reader->get_name(), name);
    ASSERT_EQ(person_reader->get_age(), 120);
    ASSERT_EQ(person_reader->get_weight(), 60);
    ASSERT_EQ(person_reader->get_active(), true);
    ASSERT_EQ(person_reader->get_gender(), NS::Gender::FEMALE);
    ASSERT_EQ(person_reader->get_profession(), NS::Profession::PILOT);

    NS::Phone::Reader phone_reader;
    person_reader->get_phones(&phone_reader, 0);
    ASSERT_EQ(phone_reader.get_number(), 144);
    person_reader->get_phones(&phone_reader, 1);
    ASSERT_EQ(phone_reader.get_number(), 143);

    NS::Address::Reader address_reader;
    person_reader->get_address(&address_reader);
    ASSERT_STREQ(address_reader.get_street(), street);
}

TEST(TestVProto, test_array_bounds)
{
    NS::Person::RootBuilder person_builder;
    person_builder.init();

    ASSERT_DEATH(person_builder.get_phones(3), "PANIC: assertion failed: \\(index < get_phones_count\\(\\)\\) \\(3 < 2\\) Array index out of bounds: Person.phones");

    NS::Person::RootReader *person_reader = person_builder.as_reader();
    NS::Phone::Reader phone_reader;
    ASSERT_DEATH(person_reader->get_phones(&phone_reader, 3), "PANIC: assertion failed: \\(index < get_phones_count\\(\\)\\) \\(3 < 2\\) Array index out of bounds: Person.phones");
}

TEST(TestVProto, test_backward_compat)
{
    NS::OldPerson::RootBuilder person_builder;
    person_builder.init();

    person_builder.set_age(120);
    person_builder.set_gender(NS::OldGender::FEMALE);
    NS::OldPhone::Builder *phone_builder = person_builder.get_phones(0);
    phone_builder->set_number(144);
    phone_builder = person_builder.get_phones(1);
    phone_builder->set_number(143);

    NS::Person::RootReader *person_reader = (NS::Person::RootReader*) &person_builder;

    // base fields
    ASSERT_EQ(person_reader->get_age(), 120);

    // new field with no default
    ASSERT_DEATH(person_reader->get_weight(), "PANIC: No default value assigned to field 'weight' of struct 'Person'");

    // new fields
    ASSERT_DEATH(person_reader->get_name(), "Array index out of bounds: Person.name");

    ASSERT_EQ(person_reader->get_active(), true);
    ASSERT_EQ(person_reader->get_profession(), NS::Profession::PILOT);

    NS::Phone::Reader phone_reader;
    person_reader->get_phones(&phone_reader, 0);
    ASSERT_EQ(phone_reader.get_number(), 144);
    ASSERT_TRUE(phone_reader.get_active());
    person_reader->get_phones(&phone_reader, 1);
    ASSERT_EQ(phone_reader.get_number(), 143);
    ASSERT_TRUE(phone_reader.get_active());

    NS::Address::Reader address_reader;
    person_reader->get_address(&address_reader);

    ASSERT_EQ(address_reader.get_number(), 999);
    ASSERT_EQ(address_reader.get_street_count(), 0);
}

TEST(TestVProto, test_to_from_builder)
{
    NS::Person::Builder first_builder;
    first_builder.init();
    first_builder.set_age(120);

    NS::Person::Reader reader;
    reader.init_from_builder(&first_builder);

    NS::Person::Builder second_builder;
    reader.to_builder(&second_builder);
    ASSERT_EQ(second_builder.get_age(), 120);
}

int main(int argc, char **argv)
{
    ::testing::FLAGS_gtest_death_test_style = "threadsafe";
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
