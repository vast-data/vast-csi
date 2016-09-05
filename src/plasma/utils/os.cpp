/* Copyright (C) Vast Data Ltd. */

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>

#include "plasma/internal.hpp"
#include "os.hpp"
#include "assert.hpp"

namespace P {

void ensure_directory_exists(const char *dir)
{
    int32_t result = mkdir(dir, 0700);
    if (result != 0)
        ASSERT_EQUAL(errno, EEXIST);
}

bool string_to_file(const char *file_path, const char *content)
{
    FILE *file = fopen(file_path, "w");
    if (file == nullptr) {
        PT_ERROR(CONTROL, "Failed to open file %s for write with errno %s", file_path, std::strerror(errno));
        return false;
    }

    if (fputs(content, file) == EOF) {
        PT_ERROR(CONTROL, "Failed to write to file %s with errno %s", file_path, std::strerror(errno));
        fclose(file);
        return false;
    }

    if (fclose(file) != 0) {
        PT_ERROR(CONTROL, "Failed to close file %s with errno %s", file_path, std::strerror(errno));
        return false;
    }

    return true;
}

bool file_to_string(const char *file_path, size_t buf_size, char *buf)
{
    FILE *file = fopen(file_path, "r");
    if (file == nullptr) {
        PT_ERROR(CONTROL, "Failed to open file %s for read with errno %s", file_path, std::strerror(errno));
        return false;
    }

    size_t res = fread(buf, 1, buf_size - 1, file);
    buf[res] = '\0';
    if (ferror(file)) {
        PT_ERROR(CONTROL, "Error reading file %s", file_path);
        return false;
    }
    if (!feof(file)) {
        PT_ERROR(CONTROL, "File %s is too big (> %lu bytes)", file_path, buf_size - 1);
        return false;
    }

    if (fclose(file) != 0) {
        PT_ERROR(CONTROL, "Failed to close file %s with errno %s", file_path, std::strerror(errno));
        return false;
    }

    return true;
}

void set_cloexec_flag(FILE *file)
{
    int fd = fileno(file);
    int flags = fcntl(fd, F_GETFD, 0);
    if (flags < 0) {  // failed reading the flags - not supposed to happen
        return;
    }
    fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
}

}  // namespace P
