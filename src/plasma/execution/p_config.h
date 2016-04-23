/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_config.h
 * \brief An interface for the environment's configuration.
 *
 * This module provides functions for manipulating configuration settings.
 * It is used by modules and components during initialization.
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

/*!
 * This function returns the number of settings in a group, or the number of elements in a list or array. For other types of settings, it panics.
 */
int32_t p_config_setting_length(PConfigSetting *setting);

/*!
 * This function fetches the element at the given index index in the setting setting, which must be an array, list, or group.
 * It returns the requested setting on success, or NULL if index is out of range or if setting is not an array, list, or group.
 */
PConfigSetting *p_config_setting_get_element(PConfigSetting *setting, uint32_t index);

/*!
 * Return the name of the given setting.
 */
const char *p_config_setting_name(PConfigSetting *setting);
