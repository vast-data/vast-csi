/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_config.h
 * \brief An interface for the environment's configuration.
 *
 * This module lets components configure themselves using configuration settings.
 */

#pragma once

#include <p.h>
#include <libconfig.h>

typedef config_setting_t PConfigSetting;

/*!
 * Return the child setting located at given path or NULL if it is not found.
 */
PConfigSetting *p_config_setting_lookup_optional(PConfigSetting *setting, const char *path);

/*!
 * Return the child setting located at given path or panic if it is not found.
 */
PConfigSetting *p_config_setting_lookup_required(PConfigSetting *setting, const char *path);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
int32_t p_config_setting_get_int32(PConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
int64_t p_config_setting_get_int64(PConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
double p_config_setting_get_float(PConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
bool p_config_setting_get_bool(PConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
const char *p_config_setting_get_string(PConfigSetting *setting);
