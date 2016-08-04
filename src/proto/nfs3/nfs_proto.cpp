#include <rpc/pmap_clnt.h>
#include "nfs_proto.hpp"
#include "rpc.hpp"
#include "mount_server.hpp"
#include "nfs_server.hpp"

#define CURRENT_COMPONENT ComponentId::NFS

using P::Net::ConnectionsManager;
using namespace P::Conf;

namespace Nfs {

/*static*/ Nfs::NfsConfig NfsProto::_nfs_conf = { 0 };

void NfsProto::init(EStore::EStore *estore, ConnectionsManager *connections_manager, bool primary_instance)
{
    if (!_nfs_conf.enabled) {
        PT_INFO("nfs not configured");
        return;
    }
    _estore = estore;
    _mount_srv = new MountServer();
    _mount_srv->init(_estore);
    _nfs_srv = new NfsServer();
    _nfs_srv->init(&_nfs_conf, _estore);
    _rpc = new Rpc();
    _rpc->init(&_nfs_conf, _estore, _mount_srv, _nfs_srv, primary_instance);

    connections_manager->add_consumer(_rpc);
}

void NfsProto::destroy()
{
    if (!_nfs_conf.enabled) {
        return;
    }
    _rpc->destroy();
    _mount_srv->destroy();
    _nfs_srv->destroy();
}

void NfsProto::poll(int timeout_ms)
{
    _rpc->poll(timeout_ms);
}

static void reg_program(uint64_t program, uint64_t ver, uint32_t port, bool reg_udp)
{
    pmap_unset(program, ver);
    pmap_set(program, ver, IPPROTO_TCP, port);
    if (reg_udp) {
        pmap_set(program, ver, IPPROTO_UDP, port);
    }
}

static uint32_t get_nfs_setting(P::Conf::ConfigSetting *nfs_setting, const char *name)
{
    return conf_setting_get_int32(conf_setting_lookup_required(nfs_setting, name));
}

void NfsProto::read_conf(P::Conf::ConfigSetting *nfs_setting)
{
    _nfs_conf.port[ProtocolType::NFS3] = get_nfs_setting(nfs_setting, "nfs_port");
    _nfs_conf.port[ProtocolType::MOUNT3] = get_nfs_setting(nfs_setting, "mount_port");
    _nfs_conf.port[ProtocolType::NLM4] = get_nfs_setting(nfs_setting, "nlm_port");
    _nfs_conf.max_read_size = get_nfs_setting(nfs_setting, "max_read_size");
    _nfs_conf.max_write_size = get_nfs_setting(nfs_setting, "max_write_size");
    _nfs_conf.connections_per_silo = get_nfs_setting(nfs_setting, "connections_per_silo");
    _nfs_conf.requests_per_silo = get_nfs_setting(nfs_setting, "requests_per_silo");
}

void NfsProto::global_init(P::Conf::ConfigSetting *nfs_setting, P::Net::ConnectionsManager *connections_manager)
{
    if (nfs_setting == nullptr) {
        _nfs_conf.enabled = false;
        return;
    }
    _nfs_conf.enabled = true;
    read_conf(nfs_setting);
    // set listen sockets
    connections_manager->listen(P::Net::SocketId::NFS, _nfs_conf.port[ProtocolType::NFS3]);
    connections_manager->listen(P::Net::SocketId::MOUNT, _nfs_conf.port[ProtocolType::MOUNT3]);
//    connections_manager->listen(P::Net::SocketId::NLM, nfs_conf.port[ProtocolType::NLM4]);

    // register with rpcbind
    reg_program(NFS_PROGRAM, NFS_V3, _nfs_conf.port[ProtocolType::NFS3], false);
    reg_program(MOUNT_PROGRAM, MOUNT_V3, _nfs_conf.port[ProtocolType::MOUNT3], true);
//    reg_program(NLM_PROGRAM, NLM_V4, nfs_conf.port[ProtocolType::NLM4], false);
}

}

