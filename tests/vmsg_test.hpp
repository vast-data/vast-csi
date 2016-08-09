/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/vmsg/vmsg.hpp"
#include "plasma/vmsg/vmsg_defs.hpp"

struct VMsgTestState {
    bool _server_shutdown;
    bool _server_shutdown_complete;
};

static const P::VMsg::EnvId CLIENT_ENV_ID = 1;
static const P::VMsg::EnvId SERVER_ENV_ID = 2;
static const uint16_t CLIENT_PORT = 5001;
static const uint16_t SERVER_PORT = 5002;

class VMsgTest {
public:
    void init();
    void destroy();
    void run_test();

    void server_test();
    void client_test();

private:
    void init_state();
    void run_env(const char *config_file);
    void do_fork();
    void run_client();
    void run_server();
    void create_config_files();
    void add_addresses(P::VMsg::EnvId id, uint16_t port);

private:
    const char *SHM_NAME = "vmsg_test";

    int _shm_fd;
    VMsgTestState *_state;
    bool _client;
    int _child_pid;

    std::atomic<uint32_t> _finished_silos;
    bool _first_silo;
    P::Sync::SpinLock _lock;
};
