/* Copyright (C) Vast Data Ltd. */

/*!
 * \file vmsg_defs.hpp
 * General definitions for the messaging infrastructure.
 * Note, BE VERY CAREFUL when changing structs and definitions as most of them go over the network and must be backward
 * compatible. The sizes of the structs are statically asserted in order to avoid unintended struct size changes.
 *
 */

#pragma once

#include <stdint.h>
#include "plasma/fiber/sync/future.hpp"
#include "plasma/data/spsc_queue.hpp"
#include "modules/module_interface.hpp"

namespace P {
namespace VMsg {

static const uint32_t VMSG_VERSION = 1;
static const int RESOLVE_TIMEOUT_MS = 1000;
static const uint8_t MAX_PRIVATE_DATA = 255;
static const uint16_t RPC_BUFFER_SIZE = 512;
static const uint16_t MAX_CONCURRENT_RPC_REQUESTS = 1024;
static const uint16_t MAX_ENVS = 32;
static const uint16_t MAX_ADDR_PER_ENV = 8;
static const uint64_t DEFUALT_MSG_TIMEOUT_USEC = SEC_TO_MICRO(60);

typedef uint8_t SiloId;
typedef uint16_t EnvId;
typedef uint32_t EnvVerifier;

struct ModuleResources {
    uint32_t num_send_buffers;
    uint32_t num_recv_buffers;
};

struct VMsgConfiguration {
    ModuleResources modules[MODULES_COUNT];
    EnvId local_env_id;
};

enum class VMsgRes : uint32_t {
    OK,
    NO_RES, // no resource available
    NOT_CONNECTED, // no connection is available to destination
    CONNECTION_REFUSED, // failed to connect to peer
    SYS_ERR // system call / library error
};

struct ModuleGUID {
    EnvId env_id;
    uint8_t reserved : 4;
    // only the first 4 bits are in use for module ids
    uint8_t module_id : 4;
    SiloId silo_id;
};
static_assert(sizeof(ModuleGUID) == 4, "ModuleGUID size should be 4 bytes");
#define TRACE_GUID(TEXT, GUID) \
    PT_DEBUG(TEXT " env_id=%hu module_id=%hhu silo_id=%hhu", GUID.env_id, GUID.module_id, GUID.silo_id)

enum class BufferType {
    // request buffer - used for sending RPC requests by clients
    REQUEST,
    // reply buffer - used for receiving replies for the RPC request sent by the client
    REPLY,
    // server buffer - used for accepting RPC requests by the server
    SERVER,
    // response buffer - used for responding to RPC requests by the server
    RESPONSE,

    COUNT
};
static const uint8_t BUFFER_TYPE_COUNT = (uint8_t)BufferType::COUNT;

struct MsgId {
    uint16_t buffer_index;
    uint8_t module_id;
    uint8_t buffer_type;
};
static_assert(sizeof(MsgId) == 4, "MsgId size should be 4 bytes");

#define TRACE_MSG_ID(TEXT, ID) \
    PT_DEBUG(TEXT " buffer_index=%hu module_id=%hhu buffer_type=%hhu", ID.buffer_index, ID.module_id, ID.buffer_type)

struct VMsgHeader {
    // sender identifier
    ModuleGUID sender;
    // destination identifier
    ModuleGUID dest;
    // internal messaging information piggy backed on top of the message header
    MsgId msg_ack;
    // verifier of the env at the time the message was sent, used for crash detection.
    EnvVerifier verifier;
    // sender msg identifier
    MsgId sender_msg_id;
    // response msg identifier
    MsgId response_msg_id;
    // size of the message payload
    uint16_t payload_size;
    // running number
    uint16_t seq_num;
    // Identifier for the operation that should be done at the destination
    uint16_t op_id;
    // length of additional internal messaging data, if tail_size is positive additional
    // information is available following the payload
    uint16_t tail_size;
};
static_assert(sizeof(VMsgHeader) == 32, "VMsgHeader size should be 32 bytes");
#define TRACE_VMSG_HEADER(MSG, HDR) \
    PT_DEBUG(MSG " header=%p silo_id=%hhu seq_num=%hu op_id=%hu", HDR, HDR->sender.silo_id, HDR->seq_num, HDR->op_id); \
    TRACE_GUID("sender guid", HDR->sender); \
    TRACE_GUID("dest guid", HDR->dest); \
    TRACE_MSG_ID("sender msg_id", HDR->sender_msg_id)

// types of information that can be piggybacked
enum class PiggybackType : uint32_t {
    MSG_ACKS
};

// acknowledgments piggyback info
struct AcksPiggyback {
    uint32_t n_acks;
    MsgId acks[];
};
static_assert(sizeof(AcksPiggyback) == 4, "AcksPiggyback size should be 4 bytes");
// container for piggybacking data
struct PiggybackData {
    PiggybackType type;
    union {
        AcksPiggyback acks;
    };
};
static_assert(sizeof(PiggybackData) == 8, "PiggybackData size should be 8 bytes");

class VMsgFuture : public FiberSync::Future {
public:
    void *buffer;
    uint32_t len;
};

template<typename T>
class VMsgFutureRes : public VMsgFuture {
public:
    T *get()
    { return (T *)buffer; }
};

// Holds the context for a pending message
struct PendingMsg {
    VMsgFuture future;
    uint64_t send_time_usec;
    uint64_t timeout_usec;
};

// Supported transport types
enum class TransportType {
    RDMA,
    TCP,
    NONE
};

// A container for a single env address
struct EnvAddress {
    char host[256];
    uint16_t port;
};

// A container for an env addresses
struct EnvAddresses {
    EnvAddress addresses[MAX_ADDR_PER_ENV];
    uint16_t n_addr;
};

// connection request information
struct ConnectionRequest {
    EnvId env_id;
    ModuleId module_id;
};

// handshake message passed between 2 envs when establishing a connection
struct Handshake {
    uint32_t vmsg_ver;
    uint32_t module_ver;
    EnvId env_id;
    ModuleId module_id;
    byte padding[5];
};
static_assert(sizeof(Handshake) == 16, "Handshake size should be 16 bytes");
static_assert(sizeof(Handshake) <= MAX_PRIVATE_DATA, "Handshake must fit into the max allowed private data");

// container for transport event information, returned transports when they are polled
struct TransportEvent {
    enum class Type : uint32_t {
        WRITE_COMPLETE,
        READ_COMPLETE,
        SEND_COMPLETE,
        MSG_RECV
    };

    TransportEvent::Type type;
    MsgId id;
    uint32_t len;
    VMsgRes status;
};

struct QueuedEvent {
    SPSCQueue::Node node;
    MsgId id;
};

#define TRACE_VMSG_EVENT(event) \
    PT_DEBUG("event: type=%d id_index=%hu module_id=%hhu len=%u status=%d", \
               event.type, event.id.buffer_index, event.id.module_id, event.len, event.status);

}
}
