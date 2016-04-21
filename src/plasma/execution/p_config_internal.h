/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_config_internal.h
 * \brief A configuration file parser and emitter based on libconfig.
 *
 * This module relies on libconfig and wraps its API (http://www.hyperrealm.com/libconfig/libconfig_manual.html)
 * All functions end up calling libconfig functions.
 *
 * This module is internal because the parsing and handling of a configuration file is only done within the environment,
 * components outside plasma use an API handling configuration settings (p_config.h).
 */

#pragma once

#include <p.h>

typedef config_t PConfig;

void p_config_init(PConfig *config);
void p_config_destroy(PConfig *config);
int32_t p_config_read_file(PConfig *config, const char *path);
int32_t p_config_read_string(PConfig *config, const char *string);
const char *p_config_error_file(PConfig *config);
int32_t p_config_error_line(PConfig *config);
const char *p_config_error_text(PConfig *config);
PConfigSetting *p_config_lookup(PConfig *config, const char *key);
