/* Copyright (C) Vast Data Ltd. */
/*!
 * \file nfs_proto.hpp
 * \brief Main class of the NFS protocol component, manages the intialization and termination of the
 *        NFS protocol classes.
 */

#pragma once

#include "plasma/execution/config.hpp"
#include "plasma/net/tcp_acceptor.hpp"
#include "nfs_defs.hpp"

namespace EStore {
class EStore;
}

namespace Nfs {

class Rpc;
class NlmServer;
class MountServer;
class NfsServer;

class NfsProto {
public:
    static constexpr int32_t DEFAULT_MAX_READ_SIZE = 1048576;
    static constexpr int32_t DEFAULT_MAX_WRITE_SIZE = 1048576;
    static constexpr int32_t DEFAULT_NFS_PORT = 2049;
    static constexpr int32_t DEFAULT_MOUNT_PORT = 20048;
    static constexpr int32_t DEFAULT_NLM_PORT = 40932;
    static constexpr int32_t DEFAULT_CONNECTIONS_PER_SILO = 256;
    static constexpr int32_t DEFAULT_REQUESTS_PER_SILO = 16;

    void init(EStore::EStore *estore, P::Net::TcpAcceptor *tcp_acceptor, bool primary_instance);

    void destroy();

    void poll();

    static void global_init(P::Conf::ConfigSetting *nfs_setting, P::Net::TcpAcceptor *tcp_acceptor);
    static void write_conf(P::Conf::ConfigSetting *nfs_setting);

    static const Nfs::NfsConfig* get_nfs_conf() { return &_nfs_conf; }

private:
    static void read_conf(P::Conf::ConfigSetting *nfs_setting);

    static Nfs::NfsConfig _nfs_conf;
    EStore::EStore *_estore;
    Rpc *_rpc;
    NlmServer *_nlm_srv;
    MountServer *_mount_srv;
    NfsServer *_nfs_srv;
    uint64_t _last_req_time;  // nano
};

}
