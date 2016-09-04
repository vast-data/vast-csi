// NOTE: this is a mock implementation of the element store API on top of a local file system
// some of the element store state is kept (xattrs / handles ) in memory so restart may cause issues.
// it is recommended to start from a clean directory

#include <cstdlib>
#include <vector>
#include <cstring>
#include "plasma/utils/assert.hpp"
#include "estore.hpp"
#include <map>
#include <sys/vfs.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <utime.h>
#include <dirent.h>
#include <set>

#define MAX_OWNER_SIZE 1024+1
// TODO use correct component once its defined
#define CURRENT_COMPONENT ComponentId::NFS
// no reason to really sync writes in the mock, enable this if we'll want to do crash tests on top of the mock
static bool do_sync = false;
// enable to drop writes in order to the protocol server performance
static bool drop_writes = false;
// enable to drop reads in order to the protocol server performance
static bool drop_reads = false;

namespace EStore {

using std::string;

// 0 is reserved
static uint64_t ROOT_HANDLE = 1;
#define ESTORE_PATH "/tmp/estore"

class Lock {
public:
    void init(const LockInfo* lock_info) {
        _lock_info = *lock_info;
        _lock_info.owner = (char *)&_owner;
        std::memcpy(&_owner, lock_info->owner, lock_info->owner_len);
    }

    bool no_overlap(const LockInfo* lock) {
        return _lock_info.end < lock->start || lock->end <= _lock_info.start;
    }

    bool overlaps(const LockInfo* lock) {
        return !no_overlap(lock);
    }

    bool can_be_taken_by(const LockInfo* lock) {
        return no_overlap(lock) || (_lock_info.exclusive == false && lock->exclusive == false);
    }

    LockInfo* get_info() {
        return &_lock_info;
    }

private:
    LockInfo _lock_info;
    char _owner[MAX_OWNER_SIZE]; // MAXNETOBJ_SZ+1
    int32_t _owner_len;
};


typedef std::vector<Lock> LocksVector;
typedef std::map<EHandle, LocksVector> LocksMap;

// container for mapping between paths, handles and open file descriptors.
class HandleContainer {
public:

    void init()
    {
        _handle_to_paths[ROOT_HANDLE].insert(ESTORE_PATH);
        _path_to_handle[ESTORE_PATH] = ROOT_HANDLE;
    }

    void destroy()
    {
        close_all_handles();
        _path_to_handle.clear();
        _handle_to_paths.clear();
        _handle_to_fd.clear();
    }

    void add_handle(const string &path, EHandle *handle)
    {
        auto iter = _path_to_handle.find(path);
        if (iter == _path_to_handle.end()) {
            // add new handle
            *handle = _current_handle++;
            PT_DEV(DATA, "new handle=%lx path=%s", *handle, path.c_str());
            _handle_to_paths[*handle].insert(path);
            _path_to_handle[path] = *handle;
        } else {
            *handle = iter->second;
        }
    }

    string get_path(EHandle handle)
    {
        auto iter = _handle_to_paths.find(handle);
        if (iter == _handle_to_paths.end()) {
            return "";
        }
        return *iter->second.begin();
    }

    EHandle get_handle(const string &path)
    {
        auto iter = _path_to_handle.find(path);
        if (iter == _path_to_handle.end()) {
            return INVALID_EHANDLE;
        }
        return iter->second;
    }

    int get_fd(EHandle handle, SystemAttr *attr)
    {
        string path = get_path(handle);
        if (path.empty()) {
            return -1;
        }
        int fd = 0;
        auto fd_iter = _handle_to_fd.find(handle);
        if (fd_iter == _handle_to_fd.end()) {
            if (_handle_to_fd.size() > MAX_FD) {
                PT_DEBUG(DATA, "MAX number of open files reached");
                close_all_handles();
                _handle_to_fd.clear();
            }
            // in NFS the owner of the file can read / write to the file even if the mode bits do not allow it
            // here we need to hack around this by temporarily changing the mode bits
            chmod(path.c_str(), S_IWUSR | S_IRUSR);
            fd = open(path.c_str(), O_RDWR);
            chmod(path.c_str(), attr->mode);
            if (fd < 0) {
                return -1;
            }
            _handle_to_fd[handle] = fd;
        } else {
            fd = fd_iter->second;
        }
        return fd;
    }

    void close_handle(EHandle handle)
    {
        int fd = 0;
        auto fd_iter = _handle_to_fd.find(handle);
        if (fd_iter != _handle_to_fd.end()) {
            int ret = ::close(fd_iter->second);
            if (ret != 0) {
                PT_INFO(DATA, "close failed");
            }
            _handle_to_fd.erase(handle);
        }
    }

    void close_all_handles()
    {
        for (auto fd : _handle_to_fd) {
            close_handle(fd.second);
        }
    }

    void remove(string path)
    {
        EHandle handle = _path_to_handle[path];
        _path_to_handle.erase(path);
        std::set<string> &paths = _handle_to_paths[handle];
        paths.erase(path);
        if (paths.empty()) {
            _handle_to_paths.erase(handle);
        }
        close_handle(handle);
    }

    void rename(string src, string dst)
    {
        remove(dst);
        auto src_iter = _path_to_handle.find(src);
        if (src_iter != _path_to_handle.end()) {
            EHandle element_handle = src_iter->second;
            _path_to_handle.erase(src_iter);
            _path_to_handle[dst] = element_handle;
            _handle_to_paths[element_handle].erase(src);
            _handle_to_paths[element_handle].insert(dst);
        } else {
            EHandle element_handle;
            add_handle(dst, &element_handle);
        }
    }

    void add_path(string path, EHandle handle)
    {
        _path_to_handle[path] = handle;
        _handle_to_paths[handle].insert(path);
    }

    LocksVector *get_locks(EHandle handle)
    {
        LocksMap::iterator it = _handle_to_locks.find(handle);
        if (it == _handle_to_locks.end())
        {
            return nullptr;
        }
        return &it->second;
    }

    LocksVector *add_locks(EHandle handle)
    {
        return &_handle_to_locks.insert(std::pair<EHandle, LocksVector>(handle, LocksVector())).first->second;
    }

private:
    static const int MAX_FD = 128;
    uint64_t _current_handle = 2;
    std::map<string, EHandle> _path_to_handle;
    std::map<EHandle, std::set<string> > _handle_to_paths;
    std::map<EHandle, int> _handle_to_fd;
    LocksMap _handle_to_locks;
};

static HandleContainer _handle_container;

typedef std::map<EHandle, std::map<std::string, std::string> > XAttrMap;
static XAttrMap _handle_to_user_xattrs;
static XAttrMap _handle_to_proto_xattrs;

static uint64_t _current_handle = 2;

void EStore::init()
{
    _data_pool.init(N_DATA_BUFFERS, DATA_BUFFER_SIZE);
    _handle_container.init();

    int ret = system("mkdir -p " ESTORE_PATH);
    ASSERT_ERRNO(ret == 0);
}

void EStore::destroy()
{
    _data_pool.destroy();
    _handle_container.destroy();
}

static EStoreRes errno_to_estore_res()
{
    switch (errno) {
        case EPERM:
            return EStoreRes::PERM_ERROR;
        case ENOENT:
            return EStoreRes::NOENT;
        case EIO:
            return EStoreRes::IO_ERROR;
        case EACCES:
            return EStoreRes::PERM_ERROR;
        case EEXIST:
            return EStoreRes::EXIST;
        case ENOTEMPTY:
            return EStoreRes::NOT_EMPTY;
        default:
            return EStoreRes::PERM_ERROR;

    }
}

static EStoreRes fill_attr(const string &path, SystemAttr *attr)
{
    struct stat stat_buf;
    int ret = lstat(path.c_str(), &stat_buf);
    if (ret != 0) {
        return errno_to_estore_res();
    }

    attr->mode = stat_buf.st_mode;
    attr->nlink = stat_buf.st_nlink;
    attr->uid = stat_buf.st_uid;
    attr->gid = stat_buf.st_gid;
    attr->size = stat_buf.st_size;
    attr->used = S_BLKSIZE * stat_buf.st_blocks;
    attr->fileid = stat_buf.st_ino;
    attr->atime = SEC_TO_NANO(stat_buf.st_atime);
    attr->mtime = SEC_TO_NANO(stat_buf.st_mtime);
    attr->ctime = SEC_TO_NANO(stat_buf.st_ctime);
    attr->create_verifier = 0;
    attr->expires = 0;
    attr->element_version = 0;
    attr->element_flags = (uint64_t)ElementFlags::NONE;
    if (S_ISDIR(stat_buf.st_mode)) {
        attr->element_flags |= (uint64_t)ElementFlags::DIR;
    }
    if (S_ISREG(stat_buf.st_mode)) {
        attr->element_flags |= (uint64_t)ElementFlags::FILE;
    }
    if (S_ISLNK(stat_buf.st_mode)) {
        attr->element_flags |= (uint64_t)ElementFlags::SYMLINK;
    }
    memset(attr->md5_hash, 0, sizeof(attr->md5_hash));
    return EStoreRes::OK;
}

EStoreRes EStore::get_root_handle(EHandle *handle)
{
    *handle = ROOT_HANDLE;
    return EStoreRes::OK;
}

static void get_xattr(EHandle handle, XAttrMap & xattr_map, ExtendedAttrs *xattrs)
{
    int index = 0;
    char *buff_ptr = xattrs->buff;
    uint32_t mem_left = xattrs->buff_size;
    xattrs->n_attrs = 0;
    auto xattr_iter = xattr_map[handle].begin();
    while (xattr_iter != xattr_map[handle].end()) {
        ExtendedAttr *attr = &xattrs->attrs[index];
        uint64_t name_len = xattr_iter->first.size() + 1 ;
        if (name_len > mem_left) {
            break;
        }
        attr->name = buff_ptr;
        strncpy(attr->name, xattr_iter->first.c_str(), mem_left);
        buff_ptr += name_len;
        mem_left -= name_len;
        uint64_t val_len = xattr_iter->second.size();
        if (val_len > mem_left) {
            break;
        }
        attr->val = buff_ptr;
        strncpy((char *)attr->val, xattr_iter->second.c_str(), mem_left);
        buff_ptr += val_len;
        mem_left -= val_len;
        xattrs->n_attrs++;
    }
}

EStoreRes EStore::get_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SystemAttr *attr,
                           ExtendedAttrs *user_xattr OUT, ExtendedAttrs *proto_xattr OUT)
{
    string path = _handle_container.get_path(handle);
    if (path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", handle);
        return EStoreRes::STALE;
    }

    if (user_xattr) {
        get_xattr(handle, _handle_to_user_xattrs, user_xattr);
    }
    if (proto_xattr) {
        get_xattr(handle, _handle_to_proto_xattrs, proto_xattr);
    }

    EStoreRes res = fill_attr(path, attr);;
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }
    return EStoreRes::OK;
}

static void set_xattr(EHandle handle, XAttrMap & xattr_map, ExtendedAttrs *xattrs)
{
    LOOP(xattrs->n_attrs, i) {
        ExtendedAttr *xattr = &xattrs->attrs[i];
        std::string attr_val((char *)xattr->val, xattr->val_size);
        xattr_map[handle][xattrs->attrs[i].name] = attr_val;
    }
}

EStoreRes EStore::set_attr(OpCallback op_cb, void *cb_ctx, EHandle handle, SettableAttr *sattr, uint64_t ctime_guard,
                           ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr, SystemAttr *pre_attr,
                           SystemAttr *post_attr)
{
    string path_str = _handle_container.get_path(handle);
    if (path_str.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", handle);
        return EStoreRes::STALE;
    }
    EStoreRes res = fill_attr(path_str, pre_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    const char *path = path_str.c_str();
    if (ctime_guard != 0 && ctime_guard != pre_attr->ctime) {
        return EStoreRes::NOT_SYNC;
    }

    int ret = 0;
    if (ret == 0 && (int)sattr->flags & (int)AttrFlag::UID) {
        ret = lchown(path, sattr->uid, (gid_t)-1);
    }
    if (ret == 0 && (int)sattr->flags & (int)AttrFlag::GID) {
        ret = lchown(path, (uid_t)-1, sattr->gid);
    }
    if (ret == 0 && !(pre_attr->element_flags & (uint64_t)ElementFlags::SYMLINK) &&
        (int)sattr->flags & (int)AttrFlag::MODE) {
        _handle_container.close_handle(handle);
        ret = chmod(path, sattr->mode);
    }
    if (ret == 0 && (int)sattr->flags & (int)AttrFlag::SIZE) {
        ret = truncate(path, sattr->size);
    }
    if (ret != 0) {
        PT_INFO(DATA, "set attr op failed");
        return errno_to_estore_res();
    }
    struct utimbuf utb;
    utb.actime = NANO_TO_SEC(pre_attr->atime);
    utb.modtime = NANO_TO_SEC(pre_attr->mtime);
    if (ret == 0 && (int)sattr->flags & (int)AttrFlag::ATIME) {
        utb.actime = NANO_TO_SEC(sattr->atime);
        ret = utime(path, &utb);
    }
    if (ret == 0 && (int)sattr->flags & (int)AttrFlag::MTIME) {
        utb.modtime = NANO_TO_SEC(sattr->mtime);
        ret = utime(path, &utb);
    }
    if (ret != 0) {
        PT_INFO(DATA, "utime failed");
        return errno_to_estore_res();
    }

    if (user_xattr) {
        set_xattr(handle, _handle_to_user_xattrs, user_xattr);
    }
    if (proto_xattr) {
        set_xattr(handle, _handle_to_proto_xattrs, proto_xattr);
    }

    res = fill_attr(path, post_attr);
    if (res != EStoreRes::OK) {
        return res;
    }

    return EStoreRes::OK;
}

EStoreRes EStore::lookup(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool case_sensitive,
                         EHandle *element, SystemAttr *element_attr, SystemAttr *parent_attr)
{
    string parent_path = _handle_container.get_path(parent);
    if (parent_path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", parent);
        return EStoreRes::STALE;
    }

    std::string path = parent_path + "/" + name;

    if (element_attr) {
        EStoreRes res = fill_attr(path, element_attr);
        if (res != EStoreRes::OK) {
            return res;
        }
    }
    _handle_container.add_handle(path, element);
    if (parent_attr) {
        EStoreRes res = fill_attr(parent_path, parent_attr);
        if (res != EStoreRes::OK) {
            return res;
        }
    }
    if (op_cb) {
        EStoreRes res = op_cb(parent_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    return EStoreRes::OK;
}

EStoreRes EStore::lookup_parent(OpCallback op_cb, void *cb_ctx, EHandle handle, EHandle *parent,
                                SystemAttr *element_attr, SystemAttr *parent_attr)
{
    if (handle == ROOT_HANDLE) {
        *parent = ROOT_HANDLE;
    } else {
        string parent_path = _handle_container.get_path(handle);
        if (parent_path.empty()) {
            PT_DEBUG(DATA, "stale handle=%lx", handle);
            return EStoreRes::STALE;
        }

        auto pos = parent_path.rfind("/");
        parent_path.resize(pos);
        *parent = _handle_container.get_handle(parent_path);
        if (*parent == INVALID_EHANDLE) {
            return EStoreRes::STALE;
        }
    }

    SystemAttr tmp_attr;
    SystemAttr *attr_ptr = element_attr != nullptr ? element_attr : &tmp_attr;
    EStoreRes res = get_attr(nullptr, nullptr, handle, attr_ptr, nullptr, nullptr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(attr_ptr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    if (parent_attr) {
        EStoreRes res = get_attr(nullptr, nullptr, *parent, parent_attr, nullptr, nullptr);
        if (res != EStoreRes::OK) {
            return res;
        }
    }
    return EStoreRes::OK;
}

EStoreRes EStore::create(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, CreateFlags flags,
                         uint64_t verifier, SettableAttr *sattr, ExtendedAttrs *user_xattr, ExtendedAttrs *proto_xattr,
                         EHandle *element_handle, SystemAttr *element_attr, SystemAttr *pre_pattr,
                         SystemAttr *post_pattr)
{
    std::string parent_path = _handle_container.get_path(parent);
    if (parent_path.empty()) {
        return EStoreRes::STALE;
    }
    EStoreRes res = fill_attr(parent_path, pre_pattr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_pattr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    int ret = 0;
    std::string path = parent_path + "/" + name;
    mode_t mode = S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH;
    if ((int)flags & (int)CreateFlags::HAS_DATA) { // file
        int open_flags = O_CREAT | O_TRUNC | O_WRONLY;
        if ((int)flags & (int)CreateFlags::DONT_OVERWRITE) {
            open_flags |= O_EXCL;
        }
        int fd = open(path.c_str(), open_flags, mode);
        if (fd < 0) {
            ret = -1;
        } else {
            close(fd);
        }
    } else if ((int)flags & (int)CreateFlags::HAS_CHILDREN) { // directory
        // directory
        ret = mkdir(path.c_str(), mode);
    } else { // symlink
        // the link path is passed as a protocol xattr
        ret = symlink((char *)proto_xattr->attrs[0].val, path.c_str());
    }
    if (ret < 0) {
        PT_DEBUG(DATA, "create op failed path=%s errno=%d", path.c_str(), errno);
        return EStoreRes::EXIST;
    }
    _handle_container.add_handle(path, element_handle);

    SystemAttr element_pre_attr;
    res = set_attr(nullptr, nullptr, *element_handle, sattr, 0, user_xattr, proto_xattr, &element_pre_attr, element_attr);
    if (res != EStoreRes::OK) {
        PT_DEBUG(DATA, "set_attr failed res=%d", res);
        return res;
    }

    res = fill_attr(parent_path, post_pattr);
    if (res != EStoreRes::OK) {
        return res;
    }

    return EStoreRes::OK;
}

static EStoreRes io_start(EHandle handle, SystemAttr *pre_attr, int *fd)
{
    string path = _handle_container.get_path(handle);
    if (path.empty()) {
        return EStoreRes::STALE;
    }
    EStoreRes res = fill_attr(path, pre_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    *fd = _handle_container.get_fd(handle, pre_attr);
    if (*fd < 0) {
        return errno_to_estore_res();
    }
    return EStoreRes::OK;
}

EStoreRes EStore::write(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs,
                        SystemAttr *pre_attr, SystemAttr *post_attr)
{
    int fd;
    EStoreRes res = io_start(handle, pre_attr, &fd);
    if (res != EStoreRes::OK) {
        PT_DEBUG(DATA, "io_start failed res=%d", res);
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    uint64_t current_offset = offset;
    LOOP(io_vecs->count, i) {
        if (!drop_writes) {
            ssize_t ret = pwrite(fd, io_vecs->iovecs[i].iov_base, io_vecs->iovecs[i].iov_len, current_offset);
            if (ret != io_vecs->iovecs[i].iov_len) {
                PT_INFO(DATA, "write failed");
                return EStoreRes::IO_ERROR;
            }
        }
        current_offset += io_vecs->iovecs[i].iov_len;
    }
    LOOP(io_vecs->count, i) {
        free_data_buffer(io_vecs->iovecs[i].iov_base);
    }
    if (do_sync) {
        int ret = fsync(fd);
        if (ret != 0) {
            PT_INFO(DATA, "fsync failed");
            return errno_to_estore_res();
        }
    }
    res = fill_attr(_handle_container.get_path(handle), post_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    return EStoreRes::OK;
}


EStoreRes EStore::read(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, P::IO::IOVecs *io_vecs,
                       uint32_t *bytes_read, bool *eof, SystemAttr *pre_attr, SystemAttr *post_attr)
{
    int fd;
    EStoreRes res = io_start(handle, pre_attr, &fd);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    *eof = false;
    *bytes_read = 0;
    uint64_t current_offset = offset;

    LOOP(io_vecs->count, i) {
        io_vecs->iovecs[i].iov_base = alloc_data_buffer();
        if (io_vecs->iovecs[i].iov_base == nullptr) {
            return EStoreRes::NO_MEM;
        }
        ssize_t ret = io_vecs->iovecs[i].iov_len;
        if (!drop_reads) {
            ret = pread(fd, io_vecs->iovecs[i].iov_base, io_vecs->iovecs[i].iov_len, current_offset);
        }
        if (ret < 0) {
            return errno_to_estore_res();
        }
        *bytes_read += ret;
        if (ret < io_vecs->iovecs[i].iov_len) {
            *eof = true;
            break;
        }
        current_offset += io_vecs->iovecs[i].iov_len;
    }

    res = fill_attr(_handle_container.get_path(handle), post_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    return EStoreRes::OK;
}

EStoreRes EStore::readdir(OpCallback op_cb, void *cb_ctx, EHandle handle, uint64_t offset, uint64_t element_version,
                          ReaddirCallback rd_cb, void *rd_ctx, const char *prefix, char delimiter,
                          uint64_t *current_element_version, SystemAttr *post_attr)
{
    string path = _handle_container.get_path(handle);
    if (path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", handle);
        return EStoreRes::STALE;
    }
    SystemAttr pre_attr;
    EStoreRes res = fill_attr(path, &pre_attr);
    if (op_cb) {
        EStoreRes res = op_cb(&pre_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    DIR *dir = opendir(path.c_str());
    if (dir == NULL) {
        PT_INFO(DATA, "open dir failed");
        return errno_to_estore_res();
    }
    seekdir(dir, offset);
    errno = 0;
    struct dirent *ent = ::readdir(dir);
    bool read_more = true;
    while (ent != NULL && read_more) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) {
            // store is not supposed to return these
            ent = ::readdir(dir);
            continue;
        }
        ReaddirEntry entry;
        entry.name = ent->d_name;
        entry.is_common_prefix = false;
        entry.offset = telldir(dir);
        _handle_container.add_handle(path + "/" + entry.name, &entry.handle);
        read_more = rd_cb(&entry, rd_ctx);
        if (read_more) {
            ent = ::readdir(dir);
        }
    }
    closedir(dir);
    res = fill_attr(path, post_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    *current_element_version = post_attr->mtime;

    return EStoreRes::OK;
}

EStoreRes EStore::link(OpCallback op_cb, void *cb_ctx, EHandle link_target, EHandle parent, const char *name,
                       SystemAttr *post_link_attr, SystemAttr *pre_pattr, SystemAttr *post_pattr)
{
    string parent_path = _handle_container.get_path(parent);
    if (parent_path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", parent);
        return EStoreRes::STALE;
    }
    string target_path = _handle_container.get_path(link_target);
    if (target_path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", parent);
        return EStoreRes::STALE;
    }

    EStoreRes res = fill_attr(parent_path, pre_pattr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_pattr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    std::string element_path = parent_path + "/" + name;
    PT_DEBUG(DATA, "creating link from element_path=%s to target_path=%s", element_path.c_str(), target_path.c_str());
    int ret = ::link(target_path.c_str(), element_path.c_str());
    if (ret != 0) {
        PT_INFO(DATA, "link failed");
        return errno_to_estore_res();
    }

    _handle_container.add_path(element_path, link_target);

    res = fill_attr(parent_path, post_pattr);
    if (res != EStoreRes::OK) {
        return res;
    }
    res = fill_attr(target_path, post_link_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    return EStoreRes::OK;
}

EStoreRes EStore::unlink(OpCallback op_cb, void *cb_ctx, EHandle parent, const char *name, bool verify_no_children,
                         SystemAttr *pre_pattr, SystemAttr *post_pattr)
{
    string parent_path = _handle_container.get_path(parent);
    if (parent_path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", parent);
        return EStoreRes::STALE;
    }
    std::string element_path = parent_path + "/" + name;
    EStoreRes res = fill_attr(parent_path, pre_pattr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_pattr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    SystemAttr element_attr;
    res = fill_attr(element_path, &element_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    int ret = 0;
    if (element_attr.element_flags & (uint64_t)ElementFlags::DIR) {
        ret = ::rmdir(element_path.c_str());
    } else {
        ret = ::unlink(element_path.c_str());
    }
    if (ret != 0) {
        PT_INFO(DATA, "element unlink failed");
        return errno_to_estore_res();
    }
    _handle_container.remove(element_path);

    res = fill_attr(parent_path, post_pattr);
    if (res != EStoreRes::OK) {
        return res;
    }
    return EStoreRes::OK;
}

EStoreRes EStore::rename(OpCallback op_cb, void *cb_ctx, EHandle src_handle, const char *src_name, EHandle dst_handle,
                         const char *dst_name, SystemAttr *pre_src_attr, SystemAttr *post_src_attr,
                         SystemAttr *pre_dst_attr, SystemAttr *post_dst_attr)
{
    std::string src_parent_path = _handle_container.get_path(src_handle);
    if (src_parent_path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", src_handle);
        return EStoreRes::STALE;
    }
    std::string dst_parent_path = _handle_container.get_path(dst_handle);
    if (dst_parent_path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", dst_handle);
        return EStoreRes::STALE;
    }

    EStoreRes res = fill_attr(src_parent_path, pre_src_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    res = fill_attr(dst_parent_path, pre_dst_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(pre_src_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
        res = op_cb(pre_dst_attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }
    std::string src_path = src_parent_path + "/" + src_name;
    std::string dst_path = dst_parent_path + "/" + dst_name;
    int ret = ::rename(src_path.c_str(), dst_path.c_str());
    if (ret != 0) {
        PT_INFO(DATA, "rename failed");
        return errno_to_estore_res();
    }
    _handle_container.rename(src_path, dst_path);

    res = fill_attr(src_parent_path, post_src_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    res = fill_attr(dst_parent_path, post_dst_attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    return EStoreRes::OK;
}

EStoreRes EStore::get_stats(OpCallback op_cb, void *cb_ctx, EHandle handle, EStoreStats *stats, SystemAttr *attr)
{
    std::string path = _handle_container.get_path(handle);
    if (path.empty()) {
        PT_DEBUG(DATA, "stale handle=%lx", handle);
        return EStoreRes::STALE;
    }
    EStoreRes res = fill_attr(path, attr);
    if (res != EStoreRes::OK) {
        return res;
    }
    if (op_cb) {
        res = op_cb(attr, cb_ctx);
        if (res != EStoreRes::OK) {
            return res;
        }
    }

    struct statfs sfs;
    int ret = statfs(path.c_str(), &sfs);
    if (ret != 0) {
        return errno_to_estore_res();
    }
    stats->free_bytes = sfs.f_bfree * sfs.f_bsize;
    stats->total_bytes = sfs.f_blocks * sfs.f_bsize;
    stats->free_elements = sfs.f_ffree;
    stats->total_elements = sfs.f_files;
    return EStoreRes::OK;
}

EStoreRes EStore::lock(OpCallback op_cb, void *cb_ctx, EHandle handle, bool block, LockInfo *lock)
{
    Lock new_lock;
    LocksVector *locks = _handle_container.get_locks(handle);

    if (locks == nullptr) {
        locks = _handle_container.add_locks(handle);
    }
    else {
        for(LocksVector::iterator l = locks->begin(); l != locks->end(); ++l) {
            if (!l->can_be_taken_by(lock))
            {
                return EStoreRes::LOCKED;
            }
        }

        for(LocksVector::iterator l = locks->begin(); l != locks->end(); ++l) {
            if (l->overlaps(lock))
            {
                locks->erase(l);
            }
        }
    }

    new_lock.init(lock);
    locks->push_back(new_lock);
    return EStoreRes::OK;
}

EStoreRes EStore::unlock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock)
{
    LocksVector* locks = _handle_container.get_locks(handle);
    if (locks == nullptr) {
        return EStoreRes::OK;
    }

    for(LocksVector::iterator l = locks->begin(); l != locks->end(); ++l) {
        if (!l->can_be_taken_by(lock))
        {
            return EStoreRes::LOCKED;
        }
    }

    for(LocksVector::iterator l = locks->begin(); l != locks->end(); ++l) {
        if (l->overlaps(lock))
        {
            locks->erase(l);
        }
    }
    return EStoreRes::OK;
}

EStoreRes EStore::test_lock(OpCallback op_cb, void *cb_ctx, EHandle handle, LockInfo *lock, LockInfo *existing_lock OUT)
{
    LocksVector* locks = _handle_container.get_locks(handle);
    if (locks == nullptr) {
        return EStoreRes::OK;
    }

    for(LocksVector::iterator l = locks->begin(); l != locks->end(); ++l) {
        if (!l->can_be_taken_by(lock))
        {
            *existing_lock = *l->get_info();
            return EStoreRes::LOCKED;
        }
    }

    return EStoreRes::OK;
}

}
