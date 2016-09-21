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

class EnvProcess {
private:
    pid_t _pid;

public:
    EnvProcess(const char *config)
    {
        _pid = fork();
        if (_pid == 0) {
            P::kill_myself_on_parent_death();
            execl("dist/env", "dist/env", config, nullptr);
        }
    }

    ~EnvProcess()
    {
        kill(_pid, 9);
        waitpid(_pid, nullptr, 0);
    }

};

}  // namespace Test
