/* Copyright (C) Vast Data Ltd. */

/*!
 * \file env.hpp
 * \brief The environment is in charge of loading the configuration and bootstrapping silos, modules and components. It is considered the 'main'.
 */
#pragma once

#include <stdint.h>
#include <limits.h>
#include <pthread.h>
#include "plasma/net/tcp_acceptor.hpp"
#include "plasma/vmsg/vmsg.hpp"

#include "plasma/utils/compiler.hpp"
#include "plasma/trace/emitter.hpp"
#include "plasma/trace/dumper.hpp"
#include "modules/module_interface.hpp"
#include "config_internal.hpp"
#include "config.hpp"

namespace P {

// forward declarations
class Silo;
namespace VMsg {
class VMsg;
}
namespace Net {
class TcpAcceptor;
}

enum class EnvState {
    INIT,
    START,
    RUN,
    ERROR
};

class Env {
public:

    static Env *get() {
        static Env env;
        return &env;
    }

    /*!
    * This function is used by silos after they finished starting and before they
    * start running. It returns once all silos finished starting (it's implemented using a barrier).
    */
    void wait_for_run_state(void);

    /*!
    * This function gets a path for a configuration file and runs the environment.
    * Most modules wait for input forever, therefore this function runs forever.
    */
    void run(const char *config_path);

    /*!
    * Called when an error happens and the env and it silos should be stopped.
    * Can be called by signal handlers or other error conditions.
    */
    void error(void);

    EnvState get_state() const { return _state; }
    void set_state(EnvState state) { _state = state; }
    uint32_t get_num_silos() const { return _num_silos; }
    VMsg::VMsg *get_vmsg() const { return _vmsg; }
    Net::TcpAcceptor *get_tcp_acceptor() const { return _tcp_acceptor; }

    void register_module(ModuleId id, ModuleFactory *factory);
    ModuleInterface *create_module(const char *name, ModuleId *id OUT);

private:

    void init(Conf::Config *config);
    void destroy();
    void start();
    void wait_for_silos();
    void init_vmsg(Conf::Config *config, uint32_t n_silos);
    void init_nfs(Conf::Config *config);

    ModuleFactory *_module_factory[(int)ModuleId::COUNT];
    char _data_dir[PATH_MAX];
    char _trace_dir[PATH_MAX];
    Silo **_silos;
    uint32_t _num_silos;
    EnvState _state;
    pthread_barrier_t _state_barrier;
    Trace::Emitter _emitter;
    Trace::Dumper _dumper;
    VMsg::VMsg *_vmsg;
    P::Net::TcpAcceptor *_tcp_acceptor;
};

}
