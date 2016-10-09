#include "plasma/utils/assert.hpp"
#include "plasma/utils/macros.hpp"
#include "name_bitmap_block.hpp"
#include "estore/defs/estore_defs.hpp"
#include "plasma/third_party/murmur3/murmur3.h"

#define CURRENT_COMPONENT ComponentId::ESTORE
#define CURRENT_CHANNEL DATA

#define SEED 0xbaba

namespace EStore {

using EStoreRes::OK;
using P::byte;

void NameBitmapBlock::init(MIOBuffer *buffer)
{
    BaseBlock::init(buffer);
    set_type(BlockType::NAME_BITMAP_BLOCK);
    set_version(INITIAL_BLOCK_VER);
    ASSERT(space_left() >= sizeof(NameHash) + sizeof(ContentHashes));
    add_used_bytes(sizeof(uint16_t));
    ZERO_LAST(ContentHashes);
}

EStoreRes NameBitmapBlock::add_name(const char *name, LAddress addr)
{
    size_t name_len = strnlen(name, get_size());
    uint32_t hash;
    MurmurHash3_x86_32(name, name_len, SEED, &hash);
    // current implementation is naive, assumes no hash collisions and always wastes 4 bytes for hash
    // TODO check for hash collisions, use only the needed number of bytes
    // Note fixing this also effects traverse here and in the content block
    uint32_t name_hash_len = sizeof(NameHash) + sizeof(hash);
    PTC_DEBUG("add name=%s name_len=%lu hash=%u addr=0x%lx used_bytes=%u", name, name_len, hash, addr.as_number(),
              get_used_bytes());
    if (space_left() < name_hash_len + sizeof(uint16_t)) {
        return EStoreRes::NO_MEM;
    }
    TRAVERSE_CONTENT(ContentHashes, content_hashes) {
        uint16_t content_hash_len = sizeof(ContentHashes) + content_hashes->len;
        if (content_hashes->content_addr.as_number() == addr.as_number()) {
            // add name to an existing content block
            if (NEXT_CONTENT(ContentHashes, content_hashes)->len != 0) {
                // make room for the new hash by moving the next content hashes forward
                byte *src = (byte *)NEXT_CONTENT(ContentHashes, content_hashes);
                byte *dst = src + name_hash_len;
                memmove(dst, src, payload_end() - src + sizeof(uint16_t));
                content_hashes->len += name_hash_len;
            } else {
                content_hashes->len += name_hash_len;
                NEXT_CONTENT(ContentHashes, content_hashes)->len = 0;
            }
            NameHash *name_hash = (NameHash*)((byte *)content_hashes + content_hash_len - sizeof(uint8_t));
            name_hash->len = sizeof(hash);
            memcpy(name_hash->hash, &hash, sizeof(hash));
            NEXT_CONTENT(NameHash, name_hash)->len = 0;

            add_used_bytes(name_hash_len);
            return OK;
        }
    }
    // exiting content not found create a new one
    uint16_t required_space = sizeof(ContentHashes) + name_hash_len + sizeof(uint8_t);
    if (space_left() < required_space) {
        return EStoreRes::NO_MEM;
    }
    ContentHashes *content_hashes = (ContentHashes *)payload_end();
    content_hashes->len = name_hash_len + sizeof(uint8_t);
    content_hashes->content_addr = addr;
    NameHash *name_hash = content_hashes->hashes;
    name_hash->len = sizeof(hash);
    memcpy(name_hash->hash, &hash, sizeof(hash));
    add_used_bytes(required_space);
    NEXT_CONTENT(NameHash, name_hash)->len = 0;
    ZERO_LAST(ContentHashes);

    return OK;
}

uint32_t NameBitmapBlock::name_hash(const char *name)
{
    uint32_t hash;
    MurmurHash3_x86_32(name, strnlen(name, PATH_MAX), SEED, &hash);
    return hash;
}

EStoreRes NameBitmapBlock::get_addr(const char *name, LAddress *addr)
{
    uint32_t hash = name_hash(name);
    TRAVERSE_CONTENT(ContentHashes, content_hashes) {
        TRAVERSE_CONTENT_FROM(NameHash, name_hash, content_hashes->hashes) {
            if (memcmp(name_hash->hash, &hash, name_hash->len) == 0) {
                *addr = content_hashes->content_addr;
                return EStoreRes::OK;
            }
        }
    }
    return EStoreRes::NOENT;
}

EStoreRes NameBitmapBlock::traverse(uint32_t start_hash, NameBitmapBlock::TraverseCallback cb, void *cb_ctx)
{
    bool found = false;
    // TODO 0 is a valid hash
    if (start_hash == 0) {
        found = true;
    }
    TRAVERSE_CONTENT(ContentHashes, content_hashes) {
        TRAVERSE_CONTENT_FROM(NameHash, name_hash, content_hashes->hashes) {
            if (!found && memcmp(name_hash->hash, &start_hash, name_hash->len) == 0) {
                found = true;
            }
            if (found) {
                EStoreRes res = cb(content_hashes->content_addr, cb_ctx);
                if (res != OK) {
                    return res;
                }
                // each content block should be returned only once
                break;
            }
        }
    }
    return OK;
}

void NameBitmapBlock::trace()
{
    int i = 0;
    TRAVERSE_CONTENT(ContentHashes, content_hashes) {
        PTC_DEBUG("content addr=0x%lx", *(uint64_t *)&content_hashes->content_addr);
        TRAVERSE_CONTENT_FROM(NameHash, name_hash, content_hashes->hashes) {
            PTC_DEBUG("hash(%d)=%u", i, *(uint32_t *)name_hash->hash);
            ++i;
        }
    }
}

}

