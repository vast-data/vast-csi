/* Copyright (C) Vast Data Ltd. */

#include "env.hpp"
#include "control/imdb/node.hpp"
#include "control/imdb/module.hpp"
#include "modules/module_interface.hpp"
#include "plasma/execution/config.hpp"
#include "plasma/execution/config_internal.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/utils/os.hpp"
#include "globals.hpp"

namespace Control {

using P::Conf::ConfigSetting;
using P::Conf::conf_setting_add;
using P::Conf::conf_setting_add_group;
using P::Conf::conf_setting_set_string;
using P::Conf::conf_setting_set_int32;
using P::Conf::conf_setting_set_bool;

/* static */ constexpr char EnvObj::DATA_DIR_PATH[];

void EnvObj::generate_config(char *buffer, size_t buf_size)
{
    P::Conf::Config *config = P::Conf::conf_init();
    ASSERT_NOT_NULL(config);
    ConfigSetting *root = P::Conf::conf_root_setting(config);
    ASSERT_NOT_NULL(root);

    ConfigSetting *data_dir = conf_setting_add(root, "data_dir", CONFIG_TYPE_STRING);
    conf_setting_set_string(data_dir, DATA_DIR_PATH);

    if (global_test_mode) {
        ConfigSetting *test_mode_setting = conf_setting_add(root, "test_mode", CONFIG_TYPE_BOOL);
        conf_setting_set_bool(test_mode_setting, true);
    }

    ConfigSetting *vmsg = conf_setting_add_group(root, "vmsg");
    ConfigSetting *env_id = conf_setting_add(vmsg, "env_id", CONFIG_TYPE_INT32);
    conf_setting_set_int32(env_id, get_id());
    ConfigSetting *port = conf_setting_add(vmsg, "port", CONFIG_TYPE_INT32);
    conf_setting_set_int32(port, get_port());
    BaseNode *node = get_parent<BaseNode>();
    ASSERT_NOT_NULL(node);
    for (int i = 0; i < node->get_base_node()->get_addresses_count(); /*++i*/) {
        ConfigSetting *local_address = conf_setting_add(vmsg, "local_address", CONFIG_TYPE_STRING);
        conf_setting_set_string(local_address, node->get_base_node()->get_addresses(i)->get_host());
        break;  // TODO: remove this to support multiple addresses. Change what the config looks like (can't have 2 "local_address" fields), and update the relevant code (and config files).
    }

    ConfigSetting *module_resources = conf_setting_add(vmsg, "module_resources", CONFIG_TYPE_LIST);

    conf_setting_add_group(root, "global_traces");

    ConfigSetting *silo_types = conf_setting_add_group(root, "silo_types");
    ConfigSetting *silos = conf_setting_add(root, "silos", CONFIG_TYPE_LIST);

    ASSERT_OP(get_silo_count(), <, P::MAX_SILOS_PER_ENV);
    for (int i = 0; i < get_silo_count(); ++i) {
        ConfigSetting *silo = conf_setting_add_group(silos, nullptr /* name */);
        ConfigSetting *type = conf_setting_add(silo, "type", CONFIG_TYPE_STRING);
        char silo_type_name[10];
        sprintf(silo_type_name, "silo_%d", i);
        conf_setting_set_string(type, silo_type_name);
        ConfigSetting *affinity = conf_setting_add(silo, "affinity", CONFIG_TYPE_INT32);
        conf_setting_set_int32(affinity, get_silos(i)->get_affinity());

        ConfigSetting *silo_type = conf_setting_add_group(silo_types, silo_type_name);
        conf_setting_add_group(silo_type, "modules");
        conf_setting_add_group(silo_type, "traces");
    }

    bool module_resources_configured[(int)ModuleId::COUNT] = { false };

    IMDB_ITER_CHILDREN(this, module, BaseModuleLogic) {
        // Update silo_types
        ConfigSetting *silo_type = P::Conf::conf_setting_get_element(silo_types,
                                                                     module->get_base_module()->get_silo_id());
        ASSERT_NOT_NULL(silo_type);
        ConfigSetting *modules = P::Conf::conf_setting_lookup_required(silo_type, "modules");
        ConfigSetting *module_config = conf_setting_add_group(modules, module_id_to_string(module->get_module_id()));
        conf_setting_add_group(module_config, "components");
        conf_setting_add(module_config, "fibers", CONFIG_TYPE_LIST);
        ModuleRegistry::get(module->get_module_id())->generate_config(module_config);

        // Update VMsg module_resources
        // TODO: once ORION-63 is handled, this should move to the fixed part of the config.
        if (!module_resources_configured[(int)module->get_module_id()]) {
            module_resources_configured[(int)module->get_module_id()] = true;
            ConfigSetting *resources = conf_setting_add_group(module_resources, nullptr /* name */);
            ConfigSetting *name = conf_setting_add(resources, "name", CONFIG_TYPE_STRING);
            conf_setting_set_string(name, module_id_to_string(module->get_module_id()));
            P::VMsg::ModuleResources vmsg_module_resources = { 0, 0 };
            ModuleRegistry::get(module->get_module_id())->get_vmsg_module_resources(&vmsg_module_resources);
            ConfigSetting *num_send_buffers = conf_setting_add(resources, "num_send_buffers", CONFIG_TYPE_INT32);
            conf_setting_set_int32(num_send_buffers, vmsg_module_resources.num_send_buffers);
            ConfigSetting *num_recv_buffers = conf_setting_add(resources, "num_recv_buffers", CONFIG_TYPE_INT32);
            conf_setting_set_int32(num_recv_buffers, vmsg_module_resources.num_recv_buffers);
        }
    }

    // Generate NFS config if there's an I-Module
    if (module_resources_configured[(P::Index)ModuleId::I]) {
        P::Env::generate_nfs_config(root);
    }

    char env_guid_str[P::GUID::STRING_SIZE];
    get_base_proto()->get_guid().to_string(env_guid_str);
    char config_file_path[PATH_MAX];
    sprintf(config_file_path, "%s/%s.config", P::Env::get()->get_data_dir(), env_guid_str);
    ASSERT(P::Conf::conf_write_file(config, config_file_path));
    P::Conf::conf_destroy(config);
    ASSERT(P::file_to_string(config_file_path, buf_size, buffer));
    ASSERT_EQUAL(0, remove(config_file_path));
}

bool EnvObj::is_platform()
{
    return get_only_child<PModuleObj>() != nullptr;
}

}  // namespace Control
