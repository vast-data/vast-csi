#include "module_interface.hpp"
#include "e_module.hpp"
#include "c_module.hpp"
#include "i_module.hpp"
#include "p_module.hpp"
#include "b_module.hpp"
#include "../tests/test_module.hpp"
#include "plasma/execution/env.hpp"

template <class Module, class ControlObj>
class ModuleFactoryImpl : public ModuleFactory {
    virtual ModuleInterface *create() { return new Module(); }
    virtual ModuleId get_id() { return Module::get_id(); }
    virtual void generate_config(P::Conf::ConfigSetting *module_config) override
    {
        Module::generate_config(module_config);
    }
    virtual void get_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources) override
    {
        Module::get_vmsg_module_resources(vmsg_module_resources);
    }

    virtual ControlObj *create_control_object(Control::TreeDB *imdb, Control::EnvObj *parent)
    {
        return imdb->create<ControlObj>(P::GUID::create(), parent);
    }
};

static ModuleFactoryImpl<TestModule, Control::TModuleObj> t;
static ModuleFactoryImpl<P::PModule, Control::PModuleObj> p;
static ModuleFactoryImpl<P::EModule, Control::EModuleObj> e;
static ModuleFactoryImpl<Control::CModule, Control::CModuleObj> c;
static ModuleFactoryImpl<BModule, Control::BModuleObj> b;
static ModuleFactoryImpl<IModule, Control::IModuleObj> i;

static ModuleFactory *factories[] = { &t, &p, &e, &c, &b, &i };

/*static*/ ModuleFactory *ModuleRegistry::get(ModuleId module_id)
{
    auto result = get_instance()->_factories[(size_t)module_id];
    ASSERT_NOT_NULL(result, "Module not initialized: " << module_id_to_string(module_id));
    return result;
}

/*static*/ void ModuleRegistry::set(ModuleFactory *factory)
{
    get_instance()->_factories[(size_t)factory->get_id()] = factory;
}

static __attribute__ ((constructor)) void init_registry()
{
    ModuleRegistry::init();
    for (auto *factory : factories) {
        ModuleRegistry::set(factory);
    }
}

/* static */ void ModuleInterface::add_fiber_group_config(P::Conf::ConfigSetting *module_config, uint32_t count,
                                                          const char *group_id,
                                                          uint32_t stack_size /* = DEFAULT_FIBER_STACK_SIZE */)
{
    P::Conf::ConfigSetting *fibers = P::Conf::conf_setting_lookup_required(module_config, "fibers");
    P::Conf::ConfigSetting *fiber_group = P::Conf::conf_setting_add_group(fibers, nullptr /* name */);

    P::Conf::ConfigSetting *count_setting = P::Conf::conf_setting_add(fiber_group, "count", CONFIG_TYPE_INT32);
    P::Conf::conf_setting_set_int32(count_setting, count);
    P::Conf::ConfigSetting *stack_size_setting = P::Conf::conf_setting_add(fiber_group, "stack_size", CONFIG_TYPE_INT32);
    P::Conf::conf_setting_set_int32(stack_size_setting, stack_size);
    P::Conf::ConfigSetting *group_id_setting = P::Conf::conf_setting_add(fiber_group, "group_id", CONFIG_TYPE_STRING);
    P::Conf::conf_setting_set_string(group_id_setting, group_id);
}

/* static */ void ModuleInterface::get_default_vmsg_module_resources(P::VMsg::ModuleResources *vmsg_module_resources) {
    vmsg_module_resources->num_send_buffers = DEFAULT_NUM_SEND_BUFFERS;
    vmsg_module_resources->num_recv_buffers = DEFAULT_NUM_RECV_BUFFERS;
    vmsg_module_resources->num_rdma_buffers = DEFAULT_NUM_RDMA_BUFFERS;
    vmsg_module_resources->size_rdma_buffers = DEFAULT_SIZE_RDMA_BUFFERS;
}
