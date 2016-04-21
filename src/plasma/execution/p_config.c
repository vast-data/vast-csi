#include <p.h>
#include "p_config_internal.h"

PConfigSetting *p_config_setting_lookup_optional(PConfigSetting *setting, const char *path)
{
    return config_lookup_from(setting, path);
}

PConfigSetting *p_config_setting_lookup_required(PConfigSetting *setting, const char *path)
{
    PConfigSetting *child = config_lookup_from(setting, path);
    P_ASSERT(child != NULL);
    return child;
}

int32_t p_config_setting_get_int32(PConfigSetting *setting)
{
    P_ASSERT(config_setting_type(setting) == CONFIG_TYPE_INT);
    return config_setting_get_int(setting);
}

int64_t p_config_setting_get_int64(PConfigSetting *setting)
{
    P_ASSERT(config_setting_type(setting) == CONFIG_TYPE_INT64);
    return config_setting_get_int64(setting);
}

double p_config_setting_get_float(PConfigSetting *setting)
{
    P_ASSERT(config_setting_type(setting) == CONFIG_TYPE_FLOAT);
    return config_setting_get_float(setting);
}

bool p_config_setting_get_bool(PConfigSetting *setting)
{
    P_ASSERT(config_setting_type(setting) == CONFIG_TYPE_BOOL);
    return config_setting_get_bool(setting);
}

const char *p_config_setting_get_string(PConfigSetting *setting)
{
    P_ASSERT(config_setting_type(setting) == CONFIG_TYPE_STRING);
    return config_setting_get_string(setting);
}

void p_config_init(PConfig *config)
{
    config_init(config);
}

void p_config_destroy(PConfig *config)
{
    config_destroy(config);
}

int32_t p_config_read_file(PConfig *config, const char *path)
{
    return config_read_file(config, path);
}

int32_t p_config_read_string(PConfig *config, const char *string)
{
    return config_read_string(config, string);
}

const char *p_config_error_file(PConfig *config)
{
    return config_error_file(config);
}

int32_t p_config_error_line(PConfig *config)
{
    return config_error_line(config);
}

const char *p_config_error_text(PConfig *config)
{
    return config_error_text(config);
}

PConfigSetting *p_config_lookup(PConfig *config, const char *key)
{
    return config_lookup(config, key);
}
