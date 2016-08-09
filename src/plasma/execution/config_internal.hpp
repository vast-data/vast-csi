/* Copyright (C) Vast Data Ltd. */

/*!
 * \file config_internal.hpp
 * \brief A configuration file parser and emitter based on libconfig.
 *
 * This module relies on libconfig and wraps its API (http://www.hyperrealm.com/libconfig/libconfig_manual.html)
 * All functions end up calling libconfig functions.
 *
 * This module is internal because the parsing and handling of a configuration file is only done within the environment,
 * components outside plasma use an API handling configuration settings (p_config.h).
 */

#pragma once

#include "config.hpp"

struct config_t;

namespace P {
namespace Conf {

typedef config_t Config;

Config *conf_init();
void conf_destroy(Config *config);
int32_t conf_read_file(Config *config, const char *path);
int32_t conf_read_string(Config *config, const char *string);
const char *conf_error_file(Config *config);
int32_t conf_error_line(Config *config);
const char *conf_error_text(Config *config);
ConfigSetting *conf_lookup(Config *config, const char *key);

}
}
