/* Copyright (C) Vast Data Ltd. */

/*!
 * \file estore.hpp
 * \brief The element store API, defines the facade of element store component.
 */

#pragma once

#include <stdint.h>
#include "plasma/utils/io.hpp"
#include "plasma/memory/pool.hpp"
#include "plasma/utils/compiler.hpp"
#include "plasma/utils/types.hpp"
#include "estore/defs/estore_defs.hpp"
#include "ingest.hpp"

namespace EStore {

class EStore {
public:
    void init(P::SiloId silo_id, ModuleId module_id, FiberGroupId rpc_fiber_group_id);
    void destroy();

    /*!
     * Intialize the element store on disk structures, may be called only once in the system life.
     */
    void create_estore();
    /*!
     * Load the element store from disk.
     */
    void load();

    /*!
     * Allocate a data buffer iovec from the element store, the buffer size is DATA_BUFFER_SIZE.
     * In case no memory is avaliable iovecs->count will be set to 0
     */
    void alloc_data_buffers(P::IO::IOVecs *iovecs INOUT);

    /*!
     * Return the data buffers to the element store.
     */
    void free_data_buffers(P::IO::IOVecs *iovecs);

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
    EStoreRes write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs,
                    SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

    /*!
     * Read data from an element, the call alloctes data buffers and the ownership of these buffers is passed to the
     * caller. The caller must eventually return the buffers to the element store by calling free_data_buffer().
     * A read call may return less bytes than the requested count in case there are not enough resources to serve the
     * request.
     *
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of the element to read from
     * \param offset - offset to read the data from
     * \param len - amount of data to read
     * \param res_vecs - input / output io vec structure containing the data buffers and their sizes
     * \param alloc_vecs - output io vec structure containing the data buffers that should be freed once the read
     *                     operation completes. Utilizes the memory passed by the io_vecs.
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
    EStoreRes read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t len,
                   P::IO::IOVecs *res_vecs INOUT, P::IO::IOVecs *alloc_vecs OUT, uint32_t *bytes_read OUT, bool *eof OUT,
                   SystemAttr *pre_attr OUT, SystemAttr *post_attr OUT);

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
    EStoreRes list_elements(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t element_version,
                            ListCallback rd_cb, void *rd_ctx, const char *prefix, char delimiter,
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

    /*!
     * Get element store statistics
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of an element within the element store
     * \param lock - information needed to to uniquely specify a lock
     * \param block - flag to indicate blocking behaviour
     * \return OK on successes
     *         LOCKED in case there is an existing lock that can't be removed
     */
    EStoreRes lock(OpCallback op_cb, void *cb_ctx, EHandle handle, bool block, LockInfo *lock);

    /*!
     * Get element store statistics
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of an element within the element store
     * \param lock - information needed to remove a previously established lock
     * \return OK on successes
     *         LOCKED in case there is an existing lock that can't be removed
     */
    EStoreRes unlock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock);

    /*!
     * Get element store statistics
     * \param op_cb - operation callback, called with the provided handle attributes
     * \param cb_ctx - callback context
     * \param handle - handle of an element within the element store
     * \param lock - information needed to remove a previously established lock
     * \param existing_lock - output existing lock and lock owner info (in case return value is LOCKED)
     * \return OK on successes
     *         LOCKED in case there is an existing lock
     */
    EStoreRes test_lock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock, LockInfo *existing_lock OUT);

private:
    Ingest _ingest;
    EStoreIO _eio;
    ShardMd _shard_md;
    HandlesTable _handles_table;
};

}
