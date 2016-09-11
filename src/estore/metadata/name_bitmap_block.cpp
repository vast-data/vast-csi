#include "plasma/utils/assert.hpp"
#include "plasma/utils/macros.hpp"
#include "name_bitmap_block.hpp"
#include "estore/defs/estore_defs.hpp"
#include "plasma/third_party/murmur3/murmur3.h"

#define CURRENT_COMPONENT ComponentId::EStore
#define SEED 0xbaba

namespace EStore {

void NameBitmapBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::NAME_BITMAP_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    ASSERT(space_left() >= sizeof(NameHash));
    add_used_bytes(sizeof(uint16_t));
    ZERO_LAST(NameHash);
}

EStoreRes NameBitmapBlock::add_name(const char *name, EAddress addr)
{
    size_t name_len = strnlen(name, get_size());
    uint32_t hash;
    MurmurHash3_x86_32(name, name_len, SEED, &hash);
    // current implementation is naive, assumes no hash collisions and always wastes 4 bytes for hash
    // TODO check for hash collisions, use only the needed number of bytes
    if (space_left() < sizeof(NameHash) + sizeof(hash) + sizeof(uint16_t)) {
        return EStoreRes::NO_MEM;
    }

    NameHash *name_hash = (NameHash *)(payload_end());
    name_hash->content_addr = addr;
    name_hash->len = sizeof(hash);
    memcpy(name_hash->hash, &hash, sizeof(hash));
    add_used_bytes(sizeof(NameHash) + name_hash->len);
    ZERO_LAST(NameHash);
    return EStoreRes::OK;
}

EStoreRes NameBitmapBlock::get_addr(const char *name, EAddress *addr)
{
    uint32_t hash;
    MurmurHash3_x86_32(name, strlen(name), SEED, &hash);
    TRAVERSE_CONTENT(NameHash, name_hash) {
        if (memcmp(name_hash->hash, &hash, name_hash->len) == 0) {
            *addr = name_hash->content_addr;
            return EStoreRes::OK;
        }
    }

    return EStoreRes::NOENT;
}

void NameBitmapBlock::trace_hashes()
{
    int i = 0;
    TRAVERSE_CONTENT(NameHash, name_hash) {
        printf("hash(%d)=0x%x addr=0x%lx\n", i, *(uint32_t *)name_hash->hash, *(uint64_t *)&name_hash->content_addr);
        ++i;
    }
}

}

