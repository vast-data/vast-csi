#include <signal.h>
#include <pthread.h>

#include "p_env.h"

static void segfault_handler(int sig)
{
    (void) sig;

    printf("===SEGFAULT===\n");
    p_show_backtrace();

    env_error();
}

/*!
 * This function registers a signal handler for SIGSEGV: when the program generates a segmentation fault,
 * print the backtrace of the current running fiber or thread.
 */
static void register_signals()
{
    signal(SIGSEGV, segfault_handler);
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
