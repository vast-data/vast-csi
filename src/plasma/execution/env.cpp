#include <plasma/utils/macros.hpp>
#include <signal.h>
#include <pthread.h>
#include <plasma/utils/assert.hpp>
#include <plasma/utils.h>
#include <plasma/memory/p_alloc.h>
#include <unistd.h>
#include <pthread.h>
#include "config_internal.hpp"
#include "config.hpp"
#include "silo.hpp"
#include "env.hpp"

using namespace P::Conf;

namespace P {

void Env::error()
{
    set_state(EnvState::ERROR);

    Silo *current_silo = Silo::get();
    LOOP(_num_silos, i)
    {
        if (current_silo != _silos[i])
            _silos[i]->halt();
    }

    pthread_kill(pthread_self(), SIGSTOP);
}

static Config *parse_config(const char *path)
{
    Config *config = conf_init();

    if (access(path, F_OK) == -1) {
        fprintf(stderr, "No such file: %s\n", path);
        goto error;
    }

    if (conf_read_file(config, path) == false) {
        fprintf(stderr, "%s:%d - %s\n", conf_error_file(config),
                conf_error_line(config), conf_error_text(config));
        goto error;
    }
    return config;

error:
    conf_destroy(config);
    exit(-1);
}

void Env::init(Config *config)
{
    ConfigSetting *data_dir_setting = conf_lookup(config, "data_dir");
    ASSERT_NOT_NULL(data_dir_setting);
    const char *data_dir = conf_setting_get_string(data_dir_setting);
    ASSERT_OP(strlen(data_dir), <, PATH_MAX, "data dir is too long");
    strcpy(_data_dir, data_dir);
    p_ensure_directory_exists(data_dir);

    ConfigSetting *silos_setting = conf_lookup(config, "silos");
    ASSERT_NOT_NULL(silos_setting);
    ConfigSetting *silo_types_setting = conf_lookup(config, "silo_types");
    ASSERT_NOT_NULL(silo_types_setting);
    _num_silos = (uint32_t) conf_setting_length(silos_setting);
    _silos = new Silo*[_num_silos];
    LOOP(_num_silos, i)
    {
        _silos[i] = new Silo();
        ConfigSetting *silo_setting = conf_setting_get_element(silos_setting, (uint32_t) i);
        ConfigSetting *silo_type_name_setting = conf_setting_lookup_required(silo_setting, "type");
        ConfigSetting *silo_affinity_setting = conf_setting_lookup_optional(silo_setting, "affinity");
        int32_t affinity =
            silo_affinity_setting == NULL ? Silo::NO_AFFINITY : conf_setting_get_int32(silo_affinity_setting);
        const char *silo_type_name = conf_setting_get_string(silo_type_name_setting);
        // SiloId is 8 bit
        ASSERT_MSG(i < Silo::INVALID_SILO_ID, "invalid silo id");
        _silos[i]->init(conf_setting_lookup_required(silo_types_setting, silo_type_name), affinity,
                        (SiloId) i, _data_dir);
    }
    // Initialize a barrier for all silos and the main thread, used for synchronizing state
    ASSERT_MSG(pthread_barrier_init(&_state_barrier, NULL, _num_silos + 1) == 0, "failed to initalize barrier");
}

void Env::destroy()
{
    delete[] _silos;
    pthread_barrier_destroy(&_state_barrier);
}

void Env::start_silos()
{
    LOOP(_num_silos, i)
    {
        _silos[i]->start();
    }
}

void Env::wait_for_silos()
{
    LOOP(_num_silos, i)
    {
        _silos[i]->join();
        _silos[i]->destroy();
    }
}

void Env::wait_for_run_state()
{
    ASSERT_MSG(_state == EnvState::START, "env should be started");
    pthread_barrier_wait(&_state_barrier);
}

void Env::run(const char *config_path)
{
    Config *config = parse_config(config_path);

    set_state(EnvState::INIT);
    init(config);
    conf_destroy(config);

    set_state(EnvState::START);
    start_silos();
    wait_for_run_state();

    set_state(EnvState::RUN);
    wait_for_silos();
    destroy();
}

}
