#/* Copyright (C) Vast Data Ltd. */
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
class MountServer;
class NfsServer;

class NfsProto {
public:
    void init(EStore::EStore *estore, P::Net::TcpAcceptor *tcp_acceptor, bool primary_instance);

    void destroy();

    void poll(int timeout_ms);

    static void global_init(P::Conf::ConfigSetting *nfs_setting, P::Net::TcpAcceptor *tcp_acceptor);

private:
    static void read_conf(P::Conf::ConfigSetting *nfs_setting);

private:
    static Nfs::NfsConfig _nfs_conf;
    EStore::EStore *_estore;
    Rpc *_rpc;
    MountServer *_mount_srv;
    NfsServer *_nfs_srv;
};

}
