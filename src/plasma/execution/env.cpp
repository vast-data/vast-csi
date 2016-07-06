/* Copyright (C) Vast Data Ltd. */
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include "plasma/trace/emitter.hpp"
#include "plasma/memory/alloc.hpp"
#include "plasma/utils/macros.hpp"
#include "plasma/utils/assert.hpp"
#include "plasma/utils/os.hpp"
#include "plasma/internal.hpp"
#include "config_internal.hpp"
#include "config.hpp"
#include "silo.hpp"
#include "env.hpp"

using namespace P::Conf;
using namespace P::VMsg;

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

    _dumper.stop();
    _dumper.wait();

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

void Env::register_module(ModuleId id, ModuleFactory *factory)
{
    _module_factory[(int)id] = factory;
}

ModuleInterface *Env::create_module(const char *name, ModuleId *id)
{
    LOOP(ModuleId::COUNT, i) {
        if (_module_factory[i] != nullptr && strcmp(_module_factory[i]->get_name(), name) == 0) {
            *id = (ModuleId) i;
            return _module_factory[i]->create();
        }
    }
    PANIC("Unknown module name " << name);
    return nullptr;
}

void Env::init_vmsg(Config *config, uint32_t n_silos)
{
    _vmsg = new VMsg::VMsg();
    ConfigSetting *env_id_setting = conf_lookup(config, "vmsg.env_id");
    ASSERT_NOT_NULL(env_id_setting);
    EnvId env_id = (EnvId)conf_setting_get_int32(env_id_setting);

    VMsgConfiguration vmsg_configuration;
    memset(&vmsg_configuration, 0, sizeof(vmsg_configuration));
    vmsg_configuration.local_env_id = env_id;
    vmsg_configuration.n_silos = n_silos;
    ConfigSetting *module_resources_settings = conf_lookup(config, "vmsg.module_resources");
    const size_t module_count = (size_t)conf_setting_length(module_resources_settings);
    LOOP(module_count, i) {
        ConfigSetting *module_setting = conf_setting_get_element(module_resources_settings, (uint32_t)i);
        ConfigSetting *name = conf_setting_lookup_required(module_setting, "name");
        ConfigSetting *send_buffers = conf_setting_lookup_required(module_setting, "num_send_buffers");
        ConfigSetting *recv_buffers = conf_setting_lookup_required(module_setting, "num_recv_buffers");
        byte module_id = (byte)module_id_from_string(conf_setting_get_string(name));
        ModuleResources *module_resources = &vmsg_configuration.modules[module_id];
        module_resources->num_send_buffers = conf_setting_get_int32(send_buffers);
        module_resources->num_recv_buffers = conf_setting_get_int32(recv_buffers);
    }

    _vmsg->init(&vmsg_configuration);

    ConfigSetting *local_address_setting = conf_lookup(config, "vmsg.local_address");
    ASSERT_NOT_NULL(local_address_setting);
    ConfigSetting *port_setting = conf_lookup(config, "vmsg.port");
    ASSERT_NOT_NULL(port_setting);
    EnvAddresses addresses;
    strcpy(addresses.addresses[0].host, conf_setting_get_string(local_address_setting));
    addresses.addresses[0].port = (uint16_t)conf_setting_get_int32(port_setting);
    addresses.n_addr = 1;
    _vmsg->set_env_addresses(env_id, &addresses);
}

void Env::init(Config *config)
{
    LOOP(ModuleId::COUNT, i) {
        _module_factory[i] = nullptr;
    }
    register_modules();

    ConfigSetting *data_dir_setting = conf_lookup(config, "data_dir");
    ASSERT_NOT_NULL(data_dir_setting);
    const char *data_dir = conf_setting_get_string(data_dir_setting);
    ASSERT_OP(strlen(data_dir), <, PATH_MAX, "data dir is too long");
    strcpy(_data_dir, data_dir);
    ensure_directory_exists(data_dir);

    snprintf(_trace_dir, PATH_MAX, "%s/traces", data_dir);
    ensure_directory_exists(_trace_dir);
    ConfigSetting *traces_setting = conf_lookup(config, "global_traces");
    _emitter.init(traces_setting, true);
    _dumper.init(traces_setting, &_emitter, _trace_dir);

    ConfigSetting *silos_setting = conf_lookup(config, "silos");
    ASSERT_NOT_NULL(silos_setting);
    ConfigSetting *silo_types_setting = conf_lookup(config, "silo_types");
    ASSERT_NOT_NULL(silo_types_setting);
    _num_silos = (uint32_t) conf_setting_length(silos_setting);
    init_vmsg(config, _num_silos);


    _silos = new Silo*[_num_silos];
    LOOP(_num_silos, i)
    {
        _silos[i] = new Silo();
        ConfigSetting *silo_setting = conf_setting_get_element(silos_setting, (uint32_t) i);
        ConfigSetting *silo_type_name_setting = conf_setting_lookup_required(silo_setting, "type");
        ConfigSetting *silo_affinity_setting = conf_setting_lookup_optional(silo_setting, "affinity");
        int32_t affinity =
            silo_affinity_setting == nullptr ? Silo::NO_AFFINITY : conf_setting_get_int32(silo_affinity_setting);
        const char *silo_type_name = conf_setting_get_string(silo_type_name_setting);
        // SiloId is 8 bit
        ASSERT(i < Silo::INVALID_SILO_ID, "invalid silo id");
        _silos[i]->init(conf_setting_lookup_required(silo_types_setting, silo_type_name),
                        affinity, (SiloId) i, _data_dir, _trace_dir);
    }
    // Initialize a barrier for all silos and the main thread, used for synchronizing state
    ASSERT(pthread_barrier_init(&_state_barrier, nullptr, _num_silos + 1) == 0, "failed to initalize barrier");
}

void Env::destroy()
{
    PT_INFO("Env stopping!");
    _vmsg->stop();
    _vmsg->destroy();
    delete _vmsg;

    _dumper.stop();
    _dumper.wait();

    delete[] _silos;
    pthread_barrier_destroy(&_state_barrier);
}

void Env::start()
{
    _emitter.set_global();
    _dumper.start();
    _vmsg->start();

    PT_INFO("Env started!");

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
    ASSERT(_state == EnvState::START, "env should be started");
    pthread_barrier_wait(&_state_barrier);
}

static void error_handler(int sig)
{
    int exit_code = 0;
    switch(sig) {
    case SIGSEGV:
        exit_code = 1;
        printf("===SEGFAULT===\n");
        break;
    case SIGABRT:
        exit_code = 2;
        printf("===PANIC===\n");
        break;
    case SIGTERM:
        exit_code = 0;
        printf("===TERMINATED===\n");
        break;
    default:
        PANIC();
    }

    P::Backtracer::show_backtrace();

    P::Env::get()->error();

    printf("===FINISH===\n");
    exit(exit_code);
}

/*!
 * This function registers a signal handler for SIGSEGV: when the program generates a segmentation fault,
 * print the backtrace of the current running fiber or thread.
 */
static void register_signals()
{
    signal(SIGSEGV, error_handler);
    signal(SIGABRT, error_handler);
    signal(SIGTERM, error_handler);
}

void Env::run(const char *config_path)
{
    register_signals();
    Config *config = parse_config(config_path);

    set_state(EnvState::INIT);
    init(config);
    conf_destroy(config);

    set_state(EnvState::START);
    start();
    wait_for_run_state();

    set_state(EnvState::RUN);
    wait_for_silos();
    destroy();
}

}
