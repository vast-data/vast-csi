#define UNW_LOCAL_ONLY
#include <libunwind.h>
#include <unistd.h>

#include "fiber/p_fiber_internal.h"

#define MAX_PATH_SIZE 256
static char path[MAX_PATH_SIZE] = "";

static char *get_path() {
    if (strlen(path) == 0)
        readlink("/proc/self/exe", path, MAX_PATH_SIZE);
    return path;
}

static void print_location(void *p) {
    char cmd[MAX_PATH_SIZE];
    snprintf(cmd, sizeof(cmd), "addr2line -afp -e %s %p", get_path(), p);
    FILE *fp = popen(cmd, "r");
    if (fp) {
        char buf[128];
        fgets(buf, sizeof(buf), fp);
        printf("%s", buf);
    }
}

void p_show_backtrace() {
    unw_cursor_t cursor; unw_context_t uc;
    unw_word_t ip, sp;

    unw_getcontext(&uc);
    unw_init_local(&cursor, &uc);

    printf("===BEGIN=TRACEBACK===\n");
    while (unw_step(&cursor) > 0) {
        unw_get_reg(&cursor, UNW_REG_IP, &ip);
        unw_get_reg(&cursor, UNW_REG_SP, &sp);
        if (ip == P_FIBER_STACK_UNDERFLOW_MAGIC)
            break;
        else
            print_location((void*) ip);
    }
    printf("===FINISH=TRACEBACK===\n");
}
