/* Copyright (C) Vast Data Ltd. */

/*!
 * \file config.hpp
 * \brief An interface for the environment's configuration.
 *
 * This module provides functions for manipulating configuration settings.
 * It is used by modules and components during initialization.
 */

#pragma once

typedef struct config_setting_t config_setting_t;

namespace P {

namespace Conf {

typedef config_setting_t ConfigSetting;

/*!
 * Return the child setting located at given path or NULL if it is not found.
 */
ConfigSetting *conf_setting_lookup_optional(ConfigSetting *setting, const char *path);

/*!
 * Return the child setting located at given path or panic if it is not found.
 */
ConfigSetting *conf_setting_lookup_required(ConfigSetting *setting, const char *path);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
int32_t conf_setting_get_int32(ConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
int64_t conf_setting_get_int64(ConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
double conf_setting_get_float(ConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
bool conf_setting_get_bool(ConfigSetting *setting);

/*!
 * Return the value of given setting. If the setting is of a different type than expected, panic.
 */
const char *conf_setting_get_string(ConfigSetting *setting);

/*!
 * This function returns the number of settings in a group, or the number of elements in a list or array. For other types of settings, it panics.
 */
int32_t conf_setting_length(ConfigSetting *setting);

/*!
 * This function fetches the element at the given index index in the setting setting, which must be an array, list, or group.
 * It returns the requested setting on success, or NULL if index is out of range or if setting is not an array, list, or group.
 */
ConfigSetting *conf_setting_get_element(ConfigSetting *setting, uint32_t index);

/*!
 * Return the name of the given setting.
 */
const char *conf_setting_name(ConfigSetting *setting);

}

}
