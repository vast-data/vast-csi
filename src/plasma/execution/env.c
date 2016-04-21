#include <p.h>
#include <unistd.h>
#include <signal.h>
#include <libconfig.h>

#include "p_config_internal.h"

static void init_config(const char *path, config_t *config)
{
    config_init(config);

    if (access(path, F_OK) == -1) {
        fprintf(stderr, "No such file: %s\n", path);
        goto error;
    }

    if (config_read_file(config, path) == CONFIG_FALSE) {
        fprintf(stderr, "%s:%d - %s\n", config_error_file(config), config_error_line(config), config_error_text(config));
        goto error;
    }
    return;

error:
    config_destroy(config);
    exit(-1);
}

static void __attribute__((noreturn)) handler(int sig)
{
    (void) sig;
    printf("===SEGFAULT===\n");
    p_show_backtrace();
    exit(-1);
}

/*!
 * This function registers a signal handler for SIGSEGV: when the program generates a segmentation fault,
 * print the backtrace of the current running fiber or thread.
 */
static void register_signals()
{
    signal(SIGSEGV, handler);
}

static void init_silos()
{
    raise(SIGSEGV);
}

int main(int argc, char **argv)
{
    config_t config;
    if (argc < 2) {
        fprintf(stderr, "%s: missing configuration file\n", argv[0]);
        return -1;
    }

    init_config(argv[1], &config);
    register_signals();
    init_silos();
    config_destroy(&config);

    /*
    const char *key = "silo_types.data_silo.modules.D.fibers.group_id";

    setting = config_lookup(&cfg, key);
    if (setting == NULL) {
        config_destroy(&cfg);
        return -1;
    }
    config_lookup_string(&cfg, key, &str);
    printf("value: %s\n", str);*/
    return 0;
}
