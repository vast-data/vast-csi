/* Copyright (C) Vast Data Ltd. */

/*!
 * \file env.h
 * \brief The environment is in charge of loading the configuration and bootstrapping silos, modules and components. It is considered the 'main'.
 */
#pragma once

#include <p.h>

typedef enum {
    ENV_STATE_INIT,
    ENV_STATE_START,
    ENV_STATE_RUN,
    ENV_STATE_ERROR,
} PEnvState;

typedef struct PEnv PEnv;

/*!
 * This function is used by silos after they finished starting and before they
 * start running. It returns once all silos finished starting (it's implemented using a barrier).
 */
void env_wait_for_run_state(void);

/*!
 * This function gets a path for a configuration file and runs the environment.
 * Most modules wait for input forever, therefore this function runs forever.
 */
void env_run(const char *config_path);

/*!
 * Called when an error happens and the env and it silos should be stopped.
 * Can be called by signal handlers or other error conditions.
 */
void env_error(void);
