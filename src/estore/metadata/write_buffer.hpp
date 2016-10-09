/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "estore/io/buffers_guard.hpp"
#include "base_block.hpp"
#include "estore/io/estore_io.hpp"
#include "estore/defs/estore_defs.hpp"
#include "plasma/utils/compiler.hpp"
#include "plasma/utils/io.hpp"

namespace EStore {

enum class WBState {
    INGEST,
    MIGRATE,
};

struct WBHeader {
    enum MDType {
        NAME_CONTENT,
        DATA_CONTENT,
        MD_BLOCK
    };

    uint64_t name_content_offset;
    uint64_t data_content_offset;
    uint64_t data_offset;
    uint64_t md_offset;
    WBState state;
};

class WBHeaderBlock : public BaseBlock {
public:

    virtual void init(MIOBuffer *buffer);
    void reset();


    uint64_t alloc_data_chunk(uint64_t len);
    uint64_t alloc_md(WBHeader::MDType type);
    uint64_t get_content_offset(WBHeader::MDType type) {
        switch (type) {
            case WBHeader::NAME_CONTENT: return get_wb_header()->name_content_offset;
            case WBHeader::DATA_CONTENT: return get_wb_header()->data_content_offset;
            default: PANIC("ho no!!!!");
        }
    }

    WBState get_wb_state() { return get_wb_header()->state; };
    void move_to_migrate_state() { get_wb_header()->state = WBState::MIGRATE; }

private:
    uint64_t alloc_internal();
    WBHeader *get_wb_header() { return (WBHeader *)payload_start(); }
};

class WriteBuffer {
public:
    void init(EStoreIO *eio, LAddress wb_addr);
    void update_address(LAddress wb_addr) { _wb_addr = wb_addr; }

    EStoreRes WARN_UNUSED reset();
    EStoreRes WARN_UNUSED move_to_migrate_state();

    EStoreRes WARN_UNUSED alloc_md_block(BuffersGuard *buffers_guard, LAddress *addr);
    // internally lock, read, modify, write, unlock, returns as output the address of the content block the name
    // was appended to
    EStoreRes WARN_UNUSED append_name_content(BuffersGuard *buffers_guard, const char *name, EHandle handle, LAddress *addr OUT);
    EStoreRes WARN_UNUSED append_data_content(BuffersGuard *buffers_guard, EHandle handle, uint64_t offset,
                                              uint32_t len, LAddress data_addr, LAddress *addr OUT);
    EStoreRes WARN_UNUSED alloc_data_chunk(BuffersGuard *buffers_guard, uint64_t len, LAddress *addr);
    LAddress get_content_addr(WBHeaderBlock *headerBlock, WBHeader::MDType type);


private:

    EStoreRes WARN_UNUSED alloc_md_internal(BuffersGuard *buffers_guard, WBHeader::MDType type, LAddress *addr);
    EStoreRes WARN_UNUSED read_md_header(BuffersGuard *buffers_guard, WBHeaderBlock *header_block);

    EStoreIO *_eio;
    LAddress _wb_addr;
};

}

