#include <rpc/pmap_clnt.h>
#include "nfs_proto.hpp"
#include "rpc.hpp"
#include "mount_server.hpp"
#include "nlm_server.hpp"
#include "nfs_server.hpp"
#include "plasma/execution/config_internal.hpp"
#include "plasma/fiber/provider.hpp"

#define CURRENT_COMPONENT ComponentId::NFS

using P::Net::TcpAcceptor;
using namespace P::Conf;

namespace Nfs {

/*static*/ Nfs::NfsConfig NfsProto::_nfs_conf = { 0 };

void NfsProto::init(EStore::EStore *estore, TcpAcceptor *tcp_acceptor, bool primary_instance)
{
    if (!_nfs_conf.enabled) {
        PT_INFO(CONTROL, "nfs not configured");
        return;
    }
    _last_req_time = P::get_time_nano();
    _estore = estore;
    _nlm_srv = new NlmServer();
    _nlm_srv->init(_estore);
    _mount_srv = new MountServer();
    _mount_srv->init(_estore);
    _nfs_srv = new NfsServer();
    _nfs_srv->init(&_nfs_conf, _estore);
    _rpc = new Rpc();
    _rpc->init(&_nfs_conf, _estore, _nlm_srv, _mount_srv, _nfs_srv, primary_instance);

    tcp_acceptor->add_consumer(_rpc);
}

void NfsProto::destroy()
{
    if (!_nfs_conf.enabled) {
        return;
    }
    _rpc->destroy();
    _nfs_srv->destroy();
    _mount_srv->destroy();
    _nlm_srv->destroy();
}

void NfsProto::poll()
{
    uint64_t now = P::get_time_nano();
    if (_rpc->poll() == 0) {  // No events
        if (NANO_TO_MILLI(now - _last_req_time) > P::Provider::IDLE_TIME_MILLI) {
            P::TimerQueues::sleep(P::Provider::IDLE_SLEEP_INTERVAL);
        }
    } else {
        _last_req_time = now;
    }
}

static void reg_program(uint64_t program, uint64_t ver, uint32_t port, bool reg_udp)
{
    pmap_unset(program, ver);
    pmap_set(program, ver, IPPROTO_TCP, port);
    if (reg_udp) {
        pmap_set(program, ver, IPPROTO_UDP, port);
    }
}

static void add_nfs_setting(P::Conf::ConfigSetting *nfs_setting, const char *name, int32_t value)
{
    ConfigSetting *setting = conf_setting_add(nfs_setting, name, CONFIG_TYPE_INT32);
    conf_setting_set_int32(setting, value);
}

static uint32_t get_nfs_setting(P::Conf::ConfigSetting *nfs_setting, const char *name)
{
    return conf_setting_get_int32(conf_setting_lookup_required(nfs_setting, name));
}

/* static */ void NfsProto::write_conf(P::Conf::ConfigSetting *nfs_setting)
{
    ASSERT_NOT_NULL(nfs_setting);
    // TODO: this will later be part of the fixed config (see ORION-63), so it's OK that it's hard-coded for now:
    add_nfs_setting(nfs_setting, "max_read_size", DEFAULT_MAX_READ_SIZE);
    add_nfs_setting(nfs_setting, "max_write_size", DEFAULT_MAX_WRITE_SIZE);
    add_nfs_setting(nfs_setting, "nfs_port", DEFAULT_NFS_PORT);
    add_nfs_setting(nfs_setting, "mount_port", DEFAULT_MOUNT_PORT);
    add_nfs_setting(nfs_setting, "nlm_port", DEFAULT_NLM_PORT);
    add_nfs_setting(nfs_setting, "connections_per_silo", DEFAULT_CONNECTIONS_PER_SILO);
    add_nfs_setting(nfs_setting, "requests_per_silo", DEFAULT_REQUESTS_PER_SILO);
}

/* static */ void NfsProto::read_conf(P::Conf::ConfigSetting *nfs_setting)
{
    _nfs_conf.port[ProtocolType::NFS3] = get_nfs_setting(nfs_setting, "nfs_port");
    _nfs_conf.port[ProtocolType::MOUNT3] = get_nfs_setting(nfs_setting, "mount_port");
    _nfs_conf.port[ProtocolType::NLM4] = get_nfs_setting(nfs_setting, "nlm_port");
    _nfs_conf.max_read_size = get_nfs_setting(nfs_setting, "max_read_size");
    _nfs_conf.max_write_size = get_nfs_setting(nfs_setting, "max_write_size");
    _nfs_conf.connections_per_silo = get_nfs_setting(nfs_setting, "connections_per_silo");
    _nfs_conf.requests_per_silo = get_nfs_setting(nfs_setting, "requests_per_silo");
}

/* static */ void NfsProto::global_init(P::Conf::ConfigSetting *nfs_setting, P::Net::TcpAcceptor *tcp_acceptor)
{
    if (nfs_setting == nullptr) {
        _nfs_conf.enabled = false;
        return;
    }
    _nfs_conf.enabled = true;
    read_conf(nfs_setting);
    // set listen sockets
    tcp_acceptor->listen(P::Net::SocketId::NFS, _nfs_conf.port[ProtocolType::NFS3]);
    tcp_acceptor->listen(P::Net::SocketId::MOUNT, _nfs_conf.port[ProtocolType::MOUNT3]);
    tcp_acceptor->listen(P::Net::SocketId::NLM, _nfs_conf.port[ProtocolType::NLM4]);

    // register with rpcbind
    reg_program(NFS_PROGRAM, NFS_V3, _nfs_conf.port[ProtocolType::NFS3], false);
    reg_program(MOUNT_PROGRAM, MOUNT_V3, _nfs_conf.port[ProtocolType::MOUNT3], true);
    reg_program(NLM_PROGRAM, NLM_V4, _nfs_conf.port[ProtocolType::NLM4], true);
}

}

