#include <signal.h>
#include <pthread.h>
#include <stdio.h>
#include "plasma/utils/assert.hpp"
#include "plasma/utils/backtrace.hpp"

#include "env.hpp"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "%s: missing configuration file\n", argv[0]);
        return -1;
    }
    P::Env::get()->run(argv[1]);
    return 0;
}
