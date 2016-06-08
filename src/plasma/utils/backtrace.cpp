#define UNW_LOCAL_ONLY
#include <libunwind.h>
#include <unistd.h>
#include <stdio.h>


#include <plasma/fiber/fiber.hpp>
#include "backtrace.hpp"

namespace P {

Backtracer::Backtracer()
{
    if (-1 == readlink("/proc/self/exe", _path, PATH_MAX))
    {
        _path[0] = '\0';
    }

    // TODO: TRACE ERROR
}

void Backtracer::print_location(void *p) {
    char cmd[PATH_MAX];
    snprintf(cmd, sizeof(cmd), "addr2line -afpC -e %s %p", _path , p);
    FILE *fp = popen(cmd, "r");
    if (fp) {
        char buf[128];
        fgets(buf, sizeof(buf), fp);
        printf("%s", buf);
        // TODO: TRACE as well
    }
}

void Backtracer::show_backtrace() {
    unw_cursor_t cursor; unw_context_t uc;
    unw_word_t ip, sp;

    unw_getcontext(&uc);
    unw_init_local(&cursor, &uc);

    Backtracer& backtracer = get_instance();
    if (backtracer._path[0] == '\0') {
        printf("===CAN'T TRACEBACK===\n");
        // TODO: Trace error
        return;
    }

    printf("===BEGIN TRACEBACK===\n");
    while (unw_step(&cursor) > 0) {
        unw_get_reg(&cursor, UNW_REG_IP, &ip);
        unw_get_reg(&cursor, UNW_REG_SP, &sp);
        if (ip == P::Fiber::STACK_UNDERFLOW_MAGIC || ip == 0)
            break;
        else
            backtracer.print_location((void*) ip);
    }
    printf("===FINISH TRACEBACK===\n");
}

}
