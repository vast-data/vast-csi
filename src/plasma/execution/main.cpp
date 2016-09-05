#include <stdio.h>

#include "env.hpp"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "%s: missing configuration file\n", argv[0]);
        return -1;
    }
    P::Env::get()->run(argv[0], argv[1]);
    return 0;
}
