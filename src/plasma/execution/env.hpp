/* Copyright (C) Vast Data Ltd. */

/*!
 * \file env.hpp
 * \brief The environment is in charge of loading the configuration and bootstrapping silos, modules and components. It is considered the 'main'.
 */
#pragma once

#include <stdint.h>
#include <limits.h>
#include <pthread.h>
#include "config.hpp"
#include "config_internal.hpp"

namespace P {

// forward declarations
class Silo;

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

private:

    void init(Conf::Config *config);
    void destroy();
    void start_silos();
    void wait_for_silos();

private:
    uint32_t _num_silos;
    Silo **_silos;
    char _data_dir[PATH_MAX];
    EnvState _state;
    pthread_barrier_t _state_barrier;
};

}