/* Copyright (C) Vast Data Ltd. */

/*!
 * \file config.hpp
 * \brief An interface for the environment's configuration.
 *
 * This module provides functions for manipulating configuration settings.
 * It is used by modules and components during initialization.
 */

#pragma once

#include <stdint.h>

struct config_setting_t;

namespace P {

namespace Conf {

typedef config_setting_t ConfigSetting;

/*!
 * Return the child setting located at given path or nullptr if it is not found.
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
 * It returns the requested setting on success, or nullptr if index is out of range or if setting is not an array, list, or group.
 */
ConfigSetting *conf_setting_get_element(ConfigSetting *setting, uint32_t index);

/*!
 * Return the name of the given setting.
 */
const char *conf_setting_name(ConfigSetting *setting);

/*!
 * Add a new child setting or element to the setting parent, which must be a group, array, or list.
 *
 * If parent is an array or list, the name parameter is ignored and may be NULL.
 * The function returns the new setting on success, or panics if parent is not a group, array, or list; or if there is
 * already a child setting of parent named name; or if type is invalid.
 * If type is a scalar type, the new setting will have a default value of 0, 0.0, false, or NULL, as appropriate.
 */
ConfigSetting *conf_setting_add(ConfigSetting *parent, const char *name, int type);

/*!
* Add a new child of type group to the setting parent, which must be a group, array, or list.
 *
 * This is just syntactic sugar over the above (conf_setting_add).
 */
ConfigSetting *conf_setting_add_group(ConfigSetting *parent, const char *name);

// The following functions set the value of the given setting to value.
// If the setting is of a different type than expected, panic.
void conf_setting_set_int32(ConfigSetting *setting, int32_t value);
void conf_setting_set_int64(ConfigSetting *setting, int64_t value);
void conf_setting_set_float(ConfigSetting *setting, double value);
void conf_setting_set_bool(ConfigSetting *setting, bool value);
void conf_setting_set_string(ConfigSetting *setting, const char* value);

}  // namespace Conf

}  // namespace P {
