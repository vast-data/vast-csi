/* Copyright (C) Vast Data Ltd. */

#pragma once

#include "plasma/utils/os.hpp"
#include "plasma/utils/types.hpp"

namespace Test {

static void create_system_guid()
{
    P::ensure_directory_exists("data");
    P::GUID guid = P::GUID::create();
    char guid_string[P::GUID::STRING_SIZE];
    guid.to_string(guid_string);
    ASSERT_TRUE(P::string_to_file("data/system.guid", guid_string));
}

static pid_t run_env(const char *config)
{
    pid_t pid = fork();
    if (pid == 0) {
        execl("dist/env", "dist/env", config, nullptr);
        return pid;
    } else {
        return pid;
    }
}

}  // namespace Test
