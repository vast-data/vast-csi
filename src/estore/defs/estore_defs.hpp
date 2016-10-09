/* Copyright (C) Vast Data Ltd. */

#pragma once

#include <stdint.h>
#include <phys/layout/address.hpp>
#include "plasma/utils/types.hpp"
#include "plasma/utils/units.hpp"
#include "plasma/utils/assert.hpp"

namespace EStore {

// TODO move to configuration file
static const uint32_t IO_ALIGNMENT = 512;
static const uint32_t N_DATA_BUFFERS = 4 * UNIT_KiB;
static const uint32_t DATA_BUFFER_SIZE = 16 * UNIT_KiB;
static const uint32_t ALLOCATED_DATA_BUFFER_SIZE = 16 * UNIT_KiB + (2 * IO_ALIGNMENT);

static const uint32_t MIO_OVERHEAD = 2; // TODO find a cleaner way to define this
static const uint32_t NVRAM_MD_BLOCK_SIZE = 4 * UNIT_KiB;
static const uint32_t NVRAM_USABLE_BLOCK_SIZE = NVRAM_MD_BLOCK_SIZE - MIO_OVERHEAD;
static const uint32_t WRITE_BUFFER_SIZE = 100 * UNIT_MiB;
static const uint32_t DATA_RANGE_SHARD_SIZE = 64 * UNIT_MiB;
static const uint32_t N_VIRTUAL_BUCKETS = UINT32_MAX;

// Element store limits
static const uint32_t MAX_LINKS = UINT32_MAX;
static const uint64_t MAX_ELEMENT_SIZE = UINT64_MAX;
// As long as we support only one this define will do
static const uint64_t ELEMENT_STORE_ID = 1;

// 0 is reserved
static uint64_t ROOT_HANDLE = 1;

typedef uint64_t VirtualBucketId;

// Protocol defined element flags, the meaning of these flags is opaque to the element store
enum class ElementFlags : uint64_t {
    NONE = 0,
    FILE = 0x1,
    DIR = 0x2,
    SYMLINK = 0x4,
    // dos attributes
    SPARSE = 0x8,
    SYSTEM = 0x10,
    HIDDEN = 0x20,
    ARCHIVE = 0x40,
    READONLY = 0x80,
};

enum class InternalFlags : uint64_t {
    NONE = 0,
    CONTAINER = 0x1,
    DATA = 0x2,
};
// Well defined element attributes (in contrast to extended attributes)
struct SystemAttr {
    // Protection mode bits (see NFS V3 spec for details)
    uint32_t mode;
    //  Number of hard links
    uint32_t nlink;
    // User id of the element owner
    uint32_t uid;
    // Group id of the of the element group
    uint32_t gid;
    // element size in bytes
    uint64_t size;
    // Number of bytes taken on disk
    uint64_t used;
    // Unique file identifier on the element store
    uint64_t fileid;
    // Last time element data was accessed
    uint64_t atime;
    // Last time element data was modified
    uint64_t mtime;
    // Last time element attributes were modified
    uint64_t ctime;
    // Used to support exclusive create semantics
    uint64_t create_verifier;
    // element expiration time
    uint64_t expires;
    // The object version when S3 versioning is enabled (might be derived from the handle)
    uint64_t element_version;
    // MD5 hash of the element
    P::byte md5_hash[16];
    // Protocol defined element flags
    uint64_t element_flags;
    // internal element store flags
    uint64_t internal_flags;
};
// TODO on disk --> static assert on size

enum AttrFlag {
    NONE = 0,
    MODE = 0x1,
    UID = 0x2,
    GID = 0x4,
    SIZE = 0x8,
    ATIME = 0x10,
    MTIME = 0x20,
    ELEMENT_FLAGS = 0x40
};
// The subset of system attributes that can be externally set, used as an argument to set attributes
struct SettableAttr {
    AttrFlag flags;
    uint32_t mode;
    uint32_t uid;
    uint32_t gid;
    uint64_t size;
    uint64_t atime;
    uint64_t mtime;
    uint64_t element_flags;
};

// A named attribute whose contents os opaque to the element store
struct ExtendedAttr {
    // null terminated attribute name
    char *name;
    // pointer to attribute contents
    void *val;
    // attribute contents size
    uint32_t val_size;
};

static const uint32_t MAX_XATTR = 32;
// container for extended attributes
struct ExtendedAttrs {
    // when passed as an output parameter buff points to a user allocated buffer with the size buff_size
    char *buff;
    uint32_t buff_size;
    uint32_t n_attrs;
    ExtendedAttr attrs[MAX_XATTR];
};

enum class EStoreRes {
    OK,
    STOP,                    // request to stop an iteration (not an error)
    PERM_ERROR,              // access to the request element is not permitted
    STALE,                   // invalid / stale handle
    NOENT,                   // name / path not found
    EXIST,                   // element already exist
    IO_ERROR,                // IO Error
    NOT_SYNC,                // update synchronization mismatch was detected during a set_attr operation
    NO_MEM,                  // out of memory
    INVAL,                   // invalid argument
    NOT_EMPTY,               // attempt to delete a non empty directory
    INVALID_ELEMENT_VERSION, // element version given to list_elements does not match the current element version
    NOT_A_CONTAINER,         // request for a container operation from an element that is not a container
    NOT_A_DATA_ELEMENT,      // request for a data operation from an element that is not a data element
    LOCKED,                  // operation is prohibited by locks held by other owner
    NOT_IN_INGEST,           // write buffer no in ingest state
    REQUIRES_WRITE_LOCK,     // read - write lock is required to rewrite some data
    DATA_CORRUPTION,         // read - CRC check failed
};

typedef uint64_t EHandle;
static const uint64_t INVALID_EHANDLE = (uint64_t)-1;

enum class BlockType : uint8_t {
    INVALID_BLOCK_TYPE = 0xff,
    NAME_RANGE_BLOCK = 0,
    DATA_RANGE_BLOCK = 1,
    NAME_BITMAP_BLOCK = 2,
    DATA_BITMAP_BLOCK = 3,
    NAME_CONTENT_BLOCK = 4,
    DATA_CONTENT_BLOCK = 5,
    HANDLE_BLOCK = 6,
    COMPOSITE_BLOCK = 7,
    WRITE_BUFFER_HEADER = 8,
    SHARD_MD_HEADER = 9,
};
static const uint16_t INITIAL_BLOCK_VER = 0;

// Structure describing an element passed to the ListCallback
struct ListEntry {
    EHandle handle;
    const char *name;
    uint16_t name_len;
    uint64_t offset;
    // when set to true this entry represents a common prefix
    bool is_common_prefix;
};

struct ListOffset {
    uint64_t bitmap_idx : 16;
    uint64_t name_hash  : 40;

    uint64_t as_number() { return *(uint64_t *)this; }
};

// Callback to provide to the list elements operation
typedef bool (*ListCallback)(ListEntry *entry, void *ctx);

// Operation callback function, provided as a parameter for most operations.
// In case the callback return code is not OK the operation fails and returns the status code returned
// by the callback.
typedef EStoreRes (*OpCallback)(SystemAttr *attr, void *ctx);

// Element creation flags
enum CreateFlags {
    NONE_CREATE_FLAGS = 0,
    // don't overwrite existing elements
    DONT_OVERWRITE = 0x1,
    // if set the new element will be allowed to contain children
    HAS_CHILDREN = 0x2,
    // if set the new element will be allowed to contain data
    HAS_DATA = 0x4
};

// Container for the element store statistics
struct EStoreStats {
    // The total size, in bytes, of the file system.
    uint64_t total_bytes;
    // The amount of free space, in bytes, in the file system.
    uint64_t free_bytes;
    // The total number of element slots in the element store.
    uint64_t total_elements;
    // The number of free element slots in the element store.
    uint64_t free_elements;
};

struct LockInfo {
    bool exclusive;
    int32_t svid;
    char *owner;
    int32_t owner_len;
    uint64_t start;
    uint64_t end;
};
typedef struct LockInfo LockInfo;

}
