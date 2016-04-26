#include <signal.h>
#include <pthread.h>

#include "p_env.h"

static void error_handler(int sig)
{
    switch(sig) {
    case SIGSEGV:
        printf("===SEGFAULT===\n");
        break;
    case SIGABRT:
        printf("===PANIC===\n");
        break;
    case SIGTERM:
        printf("===TERMINATED===\n");
        break;
    default:
        P_PANIC();
    }

    p_show_backtrace();

    env_error();
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

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "%s: missing configuration file\n", argv[0]);
        return -1;
    }
    register_signals();
    env_run(argv[1]);
    return 0;
}
