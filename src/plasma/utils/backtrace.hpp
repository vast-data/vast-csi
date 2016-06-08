/* Copyright (C) Vast Data Ltd. */

/*!
 * \file backtrace.hpp
 * \brief A fiber-aware stack tracing implementation
 */
#pragma once

#include <limits.h>

namespace P {

class Backtracer {
public:
    Backtracer(Backtracer const&) = delete;
    void operator=(Backtracer const&) = delete;

    static void show_backtrace();

private:
    char _path[PATH_MAX];

    Backtracer();
    void print_location(void *p);

    static Backtracer& get_instance()
    {
        static Backtracer instance;
        return instance;
    }
};




}

