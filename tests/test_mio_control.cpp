/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>


#include "control/imdb/dbox.hpp"
#include "control/imdb/dnode.hpp"
#include "control/mio/mioc.hpp"
#include "phys/layout/section_allocator.hpp"
#include "phys/mirrored_io/mio_agent.hpp"
#include "plasma/utils/units.hpp"

using namespace P;
using namespace Control;
using namespace MirroredIO;

static constexpr Index NUM_DBOXES = 2;
static constexpr Index NUM_DNODES = 2 * NUM_DBOXES;
static constexpr Index NUM_NVRAMS_PER_DNODE = 4;
static constexpr Index NUM_NVRAMS = NUM_DNODES * NUM_NVRAMS_PER_DNODE;
static constexpr uint64_t DEV_SIZE = 1024 * UNIT_GiB;
// don't count section zero
static constexpr uint16_t SECTION_COPIES_PER_DEV = DEV_SIZE / Layout::SectionAllocator::SECTION_SIZE - 1;

static const TypeConfig TYPE_CONFIGS[] = {{TypeId::DBox, sizeof(DBox), NUM_DBOXES},
                                          {TypeId::DNode, sizeof(DNode), NUM_DNODES},
                                          {TypeId::NVRAM, sizeof(NVRAM), NUM_NVRAMS},
                                          {TypeId::System, sizeof(System), 1}};

class TestSectionAllocation {
public:
    TestSectionAllocation() {
        LOOP(NUM_NVRAMS, i) {
            _sections_used[i] = new bool[SECTION_COPIES_PER_DEV];
            LOOP(SECTION_COPIES_PER_DEV, j) {
                _sections_used[i][j] = false;
            }
        }
    }

    ~TestSectionAllocation() {
        LOOP(NUM_NVRAMS, i) {
            delete[] _sections_used[i];
        }
    }

    void add(GUID dev_guid, uint64_t base_offset) {
        char buf[GUID::STRING_LENGTH];
        dev_guid.to_string(buf);
        Index dev_idx;
        sscanf(buf + GUID::STRING_LENGTH - 5, "%d", &dev_idx);
        EXPECT_LE(dev_idx, NUM_NVRAMS);

        uint64_t section_number = base_offset / Layout::SectionAllocator::SECTION_SIZE;
        EXPECT_LE(section_number, SECTION_COPIES_PER_DEV);

        EXPECT_FALSE(_sections_used[dev_idx][section_number]);
        _sections_used[dev_idx][section_number] = true;
        ++_num_section_copies_used;
    }

    bool *_sections_used[NUM_NVRAMS];
    uint64_t _num_section_copies_used = 0;
};  // class TestSectionAllocation

class MIOControlForTest : public MIOControl {
public:
    GUID* get_device_guids() { return _device_guids; }
    uint16_t get_num_devices() { return _num_devices; }
    bool get_section_zero_in_rebuild() { return _section_zero_in_rebuild; }
    SectionMappings* get_section_mappings() { return _section_mappings; }

    ConfigParams::RootBuilder* alloc_config() override {
        EXPECT_FALSE(_activate_called);
        EXPECT_FALSE(_alloc_config_called);
        _alloc_config_called = true;
        ConfigParams::RootBuilder *builder = new ConfigParams::RootBuilder;
        builder->init();
        return builder;
    }
    void config_sync(UNUSED BaseModuleLogic *module, ConfigParams::RootBuilder *config_params) override  {
        EXPECT_FALSE(_activate_called);
        EXPECT_TRUE(_alloc_config_called);
        _alloc_config_called = false;

        ConfigParams::RootReader *params = config_params->as_reader();
        for (uint16_t i = 0; i < params->get_num_sections(); ++i) {
            SectionConfig::Reader section_config;
            params->get_section_configs(&section_config, i);
            EXPECT_FALSE(section_config.get_in_rebuild());
            for (uint32_t mapping_idx = 0; mapping_idx < section_config.get_num_mappings(); ++mapping_idx) {
                MirroredIO::PhysicalAddress::Reader physical_address;
                section_config.get_mappings(&physical_address, mapping_idx);
                _test_section_alloc.add(physical_address.get_device_guid(), physical_address.get_base_offset());
            }
        }

        delete config_params;
    }
    void activate_sync(UNUSED BaseModuleLogic *module) override  {
        EXPECT_FALSE(_alloc_config_called);
        EXPECT_FALSE(_activate_called);
        _activate_called = true;
    }

    bool _alloc_config_called = false;
    bool _activate_called = false;
    TestSectionAllocation _test_section_alloc;
};  // class MIOControlForTest

// Tests activate() and activate_module()
TEST(TestMioControl, test_mioc)
{
    TreeDB db;
    db.init(NUM_ELEMENTS(TYPE_CONFIGS), TYPE_CONFIGS);

    GUID device_guids[NUM_NVRAMS];
    Index dev_idx = 0;

    char buf[GUID::STRING_LENGTH];
    System *system = db.create<System>(GUID::create(), nullptr);
    LOOP(NUM_DBOXES, i) {
        DBox *dbox = db.create<DBox>(GUID::create(), system);
        LOOP(2, j) {
            DNode *dnode = db.create<DNode>(GUID::create(), dbox);
            dnode->get_base_node()->set_state(NodeState::ACTIVE);
            LOOP(NUM_NVRAMS_PER_DNODE, k) {
                GUID guid;
                sprintf(buf, "00000000-0000-0000-0000-00000000%04d", dev_idx);
                guid.init_from_string(buf);
                device_guids[dev_idx] = guid;
                NVRAM *nvram = db.create<NVRAM>(device_guids[dev_idx], dnode);
                ++dev_idx;
                nvram->set_size(DEV_SIZE);
            }
        }
    }
    ASSERT_EQUAL(dev_idx, NUM_NVRAMS);

    MIOControlForTest mioc;
    mioc.init(system);
    mioc.activate();

    // Check section zero (list of devices):
    EXPECT_EQ(NUM_NVRAMS, mioc.get_num_devices());
    EXPECT_FALSE(mioc.get_section_zero_in_rebuild());
    for (dev_idx = 0; dev_idx < NUM_NVRAMS; ++dev_idx) {
        EXPECT_TRUE(mioc.get_device_guids()[dev_idx].equals(device_guids[dev_idx]));
    }

    // Check number of sections:

    uint16_t num_section_copies = NUM_NVRAMS * SECTION_COPIES_PER_DEV;

    // replication factors are (excluding section zero): 2, 2, 3, 2, 2, 3, ...
    uint16_t num_triplets = num_section_copies / (2 + 2 + 3);
    uint16_t num_sections = 3 * num_triplets;
    num_section_copies -= (num_triplets * (2 + 2 + 3));
    if (num_section_copies >= 2) {
        ++num_sections;
        num_section_copies -= 2;
        if (num_section_copies >= 2) {
            ++num_sections;
        }
    }
    ++num_sections;  // for section zero
    EXPECT_EQ(num_sections, mioc.get_num_sections());

    // Check section mappings:
    MIOControlForTest::SectionMappings* section_mappings = mioc.get_section_mappings();
    EXPECT_EQ(0, section_mappings[0].num_copies);
    TestSectionAllocation test_section_alloc;
    for (uint16_t section_idx = 1; section_idx < num_sections; ++section_idx) {
        EXPECT_FALSE(section_mappings[section_idx].in_rebuild);
        uint8_t num_copies = section_mappings[section_idx].num_copies;
        EXPECT_EQ(section_idx % 3 == 0 ? 3 : 2, num_copies);
        for (uint8_t i = 0; i < num_copies; ++i) {
            test_section_alloc.add(section_mappings[section_idx].mappings[i].device_guid,
                                   section_mappings[section_idx].mappings[i].base_offset);
        }
    }

    EXPECT_EQ(NUM_NVRAMS * SECTION_COPIES_PER_DEV, test_section_alloc._num_section_copies_used);

    mioc.activate_module(nullptr);
    EXPECT_TRUE(mioc._activate_called);

    // activate_module configures section zero too
    EXPECT_EQ(NUM_NVRAMS * (SECTION_COPIES_PER_DEV + 1), mioc._test_section_alloc._num_section_copies_used);
}
int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
