#include <p.h>
#include <unistd.h>
#include <pthread.h>
#include <libconfig.h>

#include "p_config_internal.h"
#include "p_silo.h"
#include "p_env.h"

struct PEnv {
    uint32_t num_silos;
    PSilo **silos;
    PEnvState state;
    pthread_barrier_t state_barrier;
};

static PEnv env;

static void env_set_state(PEnvState state)
{
    env.state = state;
}

static void parse_config(const char *path, PConfig *config)
{
    p_config_init(config);

    if (access(path, F_OK) == -1) {
        fprintf(stderr, "No such file: %s\n", path);
        goto error;
    }

    if (p_config_read_file(config, path) == CONFIG_FALSE) {
        fprintf(stderr, "%s:%d - %s\n", p_config_error_file(config),
                p_config_error_line(config), p_config_error_text(config));
        goto error;
    }
    return;

error:
    p_config_destroy(config);
    exit(-1);
}

static void env_init(PConfig *config)
{
    PConfigSetting *silos_setting = p_config_lookup(config, "silos");
    PConfigSetting *silo_types_setting = p_config_lookup(config, "silo_types");
    env.num_silos = (uint32_t) p_config_setting_length(silos_setting);
    env.silos = p_safe_malloc(sizeof(PSilo*) * (size_t) env.num_silos);
    LOOP(env.num_silos, i) {
        PConfigSetting *silo_setting = p_config_setting_get_element(silos_setting, (uint32_t) i);
        PConfigSetting *silo_type_name_setting = p_config_setting_lookup_required(silo_setting, "type");
        PConfigSetting *silo_affinity_setting = p_config_setting_lookup_optional(silo_setting, "affinity");
        int32_t affinity = silo_affinity_setting == NULL ? NO_AFFINITY : p_config_setting_get_int32(silo_affinity_setting);
        const char *silo_type_name = p_config_setting_get_string(silo_type_name_setting);
        env.silos[i] = p_silo_init(p_config_setting_lookup_required(silo_types_setting, silo_type_name), affinity);
    }
    // Initialize a barrier for all silos and the main thread, used for synchronizing state
    P_ASSERT(pthread_barrier_init(&env.state_barrier, NULL, env.num_silos + 1) == 0);
}

static void env_destroy()
{
    p_free(env.silos);
    pthread_barrier_destroy(&env.state_barrier);
}

static void env_start_silos()
{
    LOOP(env.num_silos, i) {
        p_silo_start(env.silos[i]);
    }
}

static void env_wait_for_silos()
{
    LOOP(env.num_silos, i) {
        p_silo_join(env.silos[i]);
        p_silo_destroy(env.silos[i]);
    }
}

void env_wait_for_run_state()
{
    P_ASSERT(env.state == ENV_STATE_START);
    pthread_barrier_wait(&env.state_barrier);
}

void env_run(const char *config_path)
{
    PConfig config;
    parse_config(config_path, &config);

    env_set_state(ENV_STATE_INIT);
    env_init(&config);
    config_destroy(&config);

    env_set_state(ENV_STATE_START);
    env_start_silos();
    env_wait_for_run_state();

    env_set_state(ENV_STATE_RUN);
    env_wait_for_silos();
    env_destroy();
}
