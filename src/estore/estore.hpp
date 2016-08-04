#/* Copyright (C) Vast Data Ltd. */

/*!
 * \file estore.hpp
 * \brief The element store API, defines the facade of element store component.
 */

#pragma once

#include <stdint.h>
#include "plasma/utils/units.hpp"
#include "plasma/utils/io.hpp"
#include "plasma/memory/pool.hpp"
#include "plasma/utils/compiler.hpp"
#include "plasma/utils/types.hpp"

namespace EStore {

// TODO move to configuration file
static const uint32_t N_DATA_BUFFERS = 4 * UNIT_KiB;
static const uint32_t DATA_BUFFER_SIZE = 64 * UNIT_KiB;
// Element store limits
static const uint32_t MAX_LINKS = UINT32_MAX;
static const uint64_t MAX_ELEMENT_SIZE = UINT64_MAX;
// As long as we support only one this define will do
static const uint64_t ELEMENT_STORE_ID = 1;

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
    // various element flags
    uint64_t element_flags;
};

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
    PERM_ERROR,              // access to the request element is not permitted
    STALE,                   // invalid / stale handle
    NOENT,                   // name / path not found
    EXIST,                   // element already exist
    IO_ERROR,                // IO Error
    NOT_SYNC,                // update synchronization mismatch was detected during a set_attr operation
    NO_MEM,                  // out of memory
    INVAL,                   // invalid argument
    NOT_EMPTY,               // attempt to delete a non empty directory
    INVALID_ELEMENT_VERSION, // element version given to readdir does not match the current element version
    NOT_A_CONTAINER,         // request to readdir from an element that is not allowed to have children
    LOCKED,                  // operation is prohibited by locks held by other owner
};

typedef uint64_t EHandle;
static const uint64_t INVALID_EHANDLE = (uint64_t)-1;

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

// Structure describing an element passed to the ReaddirCallback
struct ReaddirEntry {
    EHandle handle;
    const char *name;
    uint64_t offset;
    // when set to true this entry represents a common prefix
    bool is_common_prefix;
};
// Callback to provide to the read dir operation
typedef bool (*ReaddirCallback)(ReaddirEntry *entry, void *ctx);

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


class EStore {
public:
    void init();
    void destroy();

    /*!
     * Allocate a data buffer from the element store, the buffer size is DATA_BUFFER_SIZE.
     *
     * \return A pointer to the allocate buffer or nullptr in case no buffer is avaliable
     */
    void *alloc_data_buffer() { return _data_pool.alloc_address(); }

    /*!
     * Return a data buffer to the element store.
     * \param data_buffer pointer of the buffer to return.
     */
    void free_data_buffer(void *data_buffer) { _data_pool.free_address(data_buffer); }

    /*!
     * Returns a handle to the root of the element store
     *
     * \param handle - pointer to the returned root handle
     * \return OK on success
     */
    EStoreRes get_root_handle(EHandle *handle OUT);

    /*!
     * Returns the attributes of an element.
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle for the element to get the attributes for
     * \param attr - output attributes
     * \param user_xattr - optional output user extended attributes
     * \param proto_xattr - optional output protocol extended attributes
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     */
    EStoreRes get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr OUT,
                       ExtendedAttrs *user_xattr OUT, ExtendedAttrs *proto_xattr OUT);

    /*!
     * Sets the attributes of an element.
     * The SettableAttr.size field is used to request changes to the size of an element.
     * A value of 0 causes the element to be truncated, a value less than the current size of the element causes
     * data from new size to the end of the element to be discarded, and a size greater than the current size of
     * the element causes logically zeroed data bytes to be added to the end of the element.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle for the element to set the attributes for
     * \param sattr - structure describing which attributes to set and their values
     * \param ctime_guard - allows to verify the operation is consistent. if the provided value
     *                      differs from zero it will be compared with the current value of the
     *                      element ctime and if the values differ the operation will fail with
     *                      the NOT_SYNC return value
     * \param user_xattr - optional parameter, if provided the current user extended attributes will
     *                     be replaced with this value.
     * \param proto_xattr - optional parameter, if provided the current protocol extended attributes
     *                      will be replaced with this value.
     * \param pre_attr - element attributes prior the operation
     * \param post_attr - element attributes following the operation
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     *         NOT_SYNC in case ctime_guard differs from zero and does not match the element current ctime
     *
     * \note Setting an elemtn attribute updates the element ctime.
     * \note Changing the size of an element indirectly changes the element mtime.
     */
    EStoreRes set_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SettableAttr *sattr, uint64_t ctime_guard,
                       ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                       SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

    /*!
     * Lookup an element within a directory.
     * \param op_cb - operation callback, called with the provided parent handle attributes
     * \param cb_ctx - callback context
     * \param parent - handle for the parent of the element to lookup
     * \param name - name of the element to lookup
     * \param case_sensitive - defines if the name lookup is case sensitve or not
     * \param element - output element handle
     * \param element_attr - optional output element attributes
     * \param parent_attr - optional output parent element attributes
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     *         NOENT the provided element name does not exist
     */
    EStoreRes lookup(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool case_sensitive,
                     EHandle *element OUT, SystemAttr *element_attr OUT, SystemAttr *parent_attr OUT);

    /*!
     * Lookup a container element parent, the parent of the root element is the root element.
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle for the element to lookup the parent for
     * \param parent - output parent handle
     * \param element_attr - optional output element attributes
     * \param parent_attr - optional output parent element attributes
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     */
    EStoreRes lookup_parent(OpCallback op_cb, void *cb_ctx, EHandle handle,
                     EHandle *parent OUT, SystemAttr *element_attr OUT, SystemAttr *parent_attr OUT);

    /*!
     * Create a new element
     * \param op_cb - operation callback, called with the provided parent handle attributes
     * \param cb_ctx - callback context
     * \param parent - handle for the parent of the element
     * \param name - name of the element to create
     * \param flags - element creation flags
     * \param verifier - if set and the element does not exist the verifier will be stored. if set and the element
     *                   already exists the verifier will be compared with the stored verifier, if the verifiers match
     *                   the operation will return with an OK status otherwise it will return with EXIST.
     * \param sattr - new element attributes
     * \param user_xattr - optional user extended attributes
     * \param proto_xattr - optional protocol extended attributes
     * \param element_handle - output handle for the new element
     * \param element_attr - output attributes for the new element
     * \param pre_pattr - parent attributes prior the operation
     * \param post_pattr - parent attributes following the operation
     * \return OK on successes
     *         STALE in case the provided parent handle points to a non existing element
     *         EXIST in case the DONT_OVERWRITE element creation flag was specified, the element already exists
     *               and the provided verifier does not match the existing element verifier
     *
     * \note Creating an element updates the parent directory mtime and ctime.
     */
    EStoreRes create(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, CreateFlags flags,
                     uint64_t verifier, SettableAttr *sattr, ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                     EHandle *element_handle OUT, SystemAttr *element_attr OUT,
                     SystemAttr *pre_pattr OUT, SystemAttr *post_pattr OUT);

    /*!
     * Write data to an element.
     * The provided data buffer must have been previously allocated by a call to alloc_data_buffer(), in case the call
     * returns OK the ownership of the provided data buffers moves to the element store.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of the element to write to
     * \param offset - offset to write the data to
     * \param io_vecs - io vec structure containing the data buffers and their sizes
     * \param pre_attr - element attributes prior the operation
     * \param post_attr - element attributes following the operation
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     *         IO_ERROR in case the element store fails to write the data to stable storage
     *
     * \note A write operation of more than 0 bytes updates the element mtime.
     * \note A write operation that changes the element size updates the element ctime.
     */
    EStoreRes write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IOVecs *io_vecs,
                    SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

    /*!
     * Read data from an element, the call alloctes data buffers and the ownership of these buffers is passed to the
     * caller. The caller must eventually return the buffers to the element store by calling free_data_buffer().
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of the element to read from
     * \param offset - offset to read the data from
     * \param io_vecs - io vec structure containing the data buffers and their sizes
     * \param bytes_read - output parameter containing how much data was actually read
     * \param eof - output parameter specifying if the read operation have reached to end of the element data
     * \param pre_attr - element attributes prior the operation
     * \param post_attr - element attributes following the operation
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     *         IO_ERROR in case the element store fails to write the data to stable storage
     *
     * \note A read operation updates the element access time.
     */
    EStoreRes read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IOVecs *io_vecs,
                   uint32_t *bytes_read OUT, bool *eof OUT, SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

    /*!
     * Read a container element contents.
     * The operation traverses the element children and calls the proivded ReaddirCallback for each of the
     * Element children until the callback returns false.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of the element to read its children
     * \param offset - offset to start the read from, if set to 0 the scan will start from the first child element.
     *                 Otherwise the offset must be set to a value that was returned by a readdir entry
     *                 from a previous call.
     * \param element_version - version of the element, if the provided value differes from and does not match the
     *                          current_element_version the call with return with INVALID_ELEMENT_VERSION.
     * \param rd_cb - readdir callback, will be called for each of the element children until it returns false.
     * \param rd_ctx - readdir callback context.
     * \param prefix - optional parameter, if specified the call will only return elements whose name start with the
     *                 given prefix.
     * \param delimiter - optional parameter, if differs from 0 and a prefix is specified, all keys that contain the
     *                    same string between the prefix and the first occurrence of the delimiter after the prefix are
     *                    grouped as a single ReaddirEntry with the is_common_prefix flag set to true.
     *                    If a prefix parameter is not specified, the substring starts at the beginning of the key.
     * \param current_element_version output parameter containing the current element version.
     * \param post_attr - element attributes following the operation
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     *         INVALID_ELEMENT_VERSION in case the given element_version differs from 0 and does not match the current
     *                                 element_version
     *         NOT_A_CONTAINER in case the provided handle points to an element that is not allowed to contain children
     */
    EStoreRes readdir(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t element_version,
                      ReaddirCallback rd_cb, void *rd_ctx, const char *prefix, char delimiter,
                      uint64_t *current_element_version, SystemAttr *post_attr OUT);

    /*!
     * Creates a link (i.e. an additional name) to an existing element.
     * The link operation increments the nlink element attribute by 1.
     * In case the target name exists the operation will fail with EXIST.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param link_target - handle for the existing element to create a link to
     * \param parent - parent handle for the additional element name
     * \param name - the additional element name
     * \param post_link_attr - output parameter, linked element attributes following the operation
     * \param pre_pattr - parent attributes prior the operation
     * \param post_pattr - parent attributes following the operation
     * \return OK on successes
     *         STALE in case the provided link_target handle or parent handle points to a non existing element
     *         EXIST in case the new name already exists
     *
     * \note Creating a link updates the parent directory mtime and ctime.
     * \note Creating a link updates the ctime of the linked element.
     */
    EStoreRes link(OpCallback op_cb, void *cb_ctx, EHandle link_target, EHandle parent, const char *name,
                   SystemAttr *post_link_attr OUT, SystemAttr *pre_pattr OUT, SystemAttr *post_pattr OUT);

    /*!
     * Unlink an element, i.e. deletes the name entry from the parent directory.
     * If this name entry was the last reference to the corresponding element, the element may be destroyed.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param parent - handle to the parent of the name entry to unlink
     * \param name - name entry to unlink
     * \param verify_no_children - if set to true and the element has children the operation will fail with NOT_EMPTY.
     * \param pre_pattr - parent attributes prior the operation
     * \param post_pattr - parent attributes following the operation
     * \return OK on successes
     *         STALE in case the provided parent handle points to a non existing element
     *         NOT_EMPTY if verify_no_children is set to true and the element has children
     *
     * \note Unlink updates the parent directory mtime and ctime.
     */
    EStoreRes unlink(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool verify_no_children,
                     SystemAttr *pre_pattr OUT, SystemAttr *post_pattr OUT);

    /*!
     * Rename an element.
     * If the destination element already contains an entry with the destination name the source element must be
     * compatible with the destination: either both are not containers or both are containers and the destination must
     * be empty. If compatible, the existing target is removed before the rename occurs.
     * If they are not compatible or if the destination is a container but not empty, the operation fails with EXIST.
     * If src and dst both refer to the same element (they might be hard links of each other), then RENAME performs no
     * action and return OK.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param src_handle - handle to the source (old) parent element
     * \param src_name - source (old) name
     * \param dst_handle - handle to the destination (new) parent element
     * \param dst_name - destination (new) name
     * \param pre_src_attr - source parent attributes prior the operation
     * \param post_src_attr source parent attributes following the operation
     * \param pre_dst_attr - destination parent attributes prior the operation
     * \param post_dst_attr - destination parent attributes following the operation
     * \return OK on successes
     *         STALE in case the provided parent handle(s) points to a non existing element
     *         EXIST in case the destination exists and the source and destination are not compatible.
     *
     * \note Rename updates both the src and the dest parent directories mtime and ctime.
     */
    EStoreRes rename(OpCallback op_cb, void *cb_ctx, EHandle src_handle, const char *src_name,
                     EHandle dst_handle, const char *dst_name, SystemAttr *pre_src_attr OUT, 
                     SystemAttr *post_src_attr OUT, SystemAttr *pre_dst_attr OUT, SystemAttr *post_dst_attr OUT);

    /*!
     * Get element store statistics
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of an element within the element store (typically the root)
     * \param stats - output element store statistics
     * \param attr - output element attributes
     * \return OK on successes
     *         STALE in case the provided handle points to a non existing element
     */
    EStoreRes get_stats(OpCallback op_cb, void *cb_ctx, EHandle handle, EStoreStats *stats OUT, SystemAttr *attr OUT);
    
    EStoreRes lock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock);

    EStoreRes unlock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock);

    EStoreRes test_lock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock, LockInfo *existing_lock OUT);

private:
    P::Pool _data_pool;
};

}
