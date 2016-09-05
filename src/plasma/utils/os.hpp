/* Copyright (C) Vast Data Ltd. */

/*!
 * \file os.hpp
 * \brief A collection of useful OS-related utilities
 */

#pragma once

#include <stdio.h>

namespace P {

// Create a directory if one doesn't exist.
void ensure_directory_exists(const char *dir);

// Create a file and write the given string.
// Return value indicates success.
bool string_to_file(const char *file_path, const char *content);

// Read from the file at the given path into the given buffer.
// Return value indicates success (will fail if the file is larger than the buffer).
bool file_to_string(const char *file_path, size_t buf_size, char *buf);

// Enable the O_CLOEXEC flag on the given file, so that it will be automatically closed after fork/exec.
void set_cloexec_flag(FILE *fd);

}  // namespace P
