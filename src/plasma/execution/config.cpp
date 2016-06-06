#include <plasma/utils/assert.hpp>
#include "config.hpp"
#include "config_internal.hpp"

#include <libconfig.h>

namespace P {

namespace Conf {

ConfigSetting *conf_setting_lookup_optional(ConfigSetting *setting, const char *path)
{
    return config_lookup_from(setting, path);
}

ConfigSetting *conf_setting_lookup_required(ConfigSetting *setting, const char *path)
{
    ConfigSetting *child = config_lookup_from(setting, path);
    ASSERT_NOT_NULL(child);
    return child;
}

int32_t conf_setting_get_int32(ConfigSetting *setting)
{
    ASSERT_EQUAL(config_setting_type(setting), CONFIG_TYPE_INT);
    return config_setting_get_int(setting);
}

int64_t conf_setting_get_int64(ConfigSetting *setting)
{
    ASSERT_EQUAL(config_setting_type(setting), CONFIG_TYPE_INT64);
    return config_setting_get_int64(setting);
}

double conf_setting_get_float(ConfigSetting *setting)
{
    ASSERT_EQUAL(config_setting_type(setting), CONFIG_TYPE_FLOAT);
    return config_setting_get_float(setting);
}

bool conf_setting_get_bool(ConfigSetting *setting)
{
    ASSERT_EQUAL(config_setting_type(setting), CONFIG_TYPE_BOOL);
    return config_setting_get_bool(setting);
}

const char *conf_setting_get_string(ConfigSetting *setting)
{
    ASSERT_EQUAL(config_setting_type(setting), CONFIG_TYPE_STRING);
    return config_setting_get_string(setting);
}

int32_t conf_setting_length(ConfigSetting *setting)
{
    ASSERT(config_setting_type(setting) == CONFIG_TYPE_GROUP ||
           config_setting_type(setting) == CONFIG_TYPE_LIST ||
           config_setting_type(setting) == CONFIG_TYPE_ARRAY, "config type should be of the type group, list or array");
    return config_setting_length(setting);
}

ConfigSetting *conf_setting_get_element(ConfigSetting *setting, uint32_t index)
{
    return config_setting_get_elem(setting, index);
}

const char *conf_setting_get_name(ConfigSetting *setting)
{
    return config_setting_name(setting);
}

Config *conf_init()
{
    Config *conf = (Config *) malloc(sizeof(Config));
    config_init(conf);
    return conf;
}

void conf_destroy(Config *config)
{
    config_destroy(config);
    free(config);
}

int32_t conf_read_file(Config *config, const char *path)
{
    return config_read_file(config, path);
}

int32_t conf_read_string(Config *config, const char *string)
{
    return config_read_string(config, string);
}

const char *conf_error_file(Config *config)
{
    return config_error_file(config);
}

int32_t conf_error_line(Config *config)
{
    return config_error_line(config);
}

const char *conf_error_text(Config *config)
{
    return config_error_text(config);
}

ConfigSetting *conf_lookup(Config *config, const char *key)
{
    return config_lookup(config, key);
}

}

}
