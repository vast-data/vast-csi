/* Copyright (C) Vast Data Ltd. */

/*!
 * \file runnable.hpp
 * \brief A common fiber run function wrapper
 */
#pragma once

class IRunnable {
public:
    virtual void run() = 0;
    virtual ~IRunnable() = default;
};

// assuming arg is of type T*, and T derives from IRunnable
template <typename T>
void runner(void* arg)
{
    static_assert(std::is_base_of<IRunnable, T>::value, "T must extend Runnable!");
    IRunnable *r = (IRunnable*)arg;
    r->run();
}
