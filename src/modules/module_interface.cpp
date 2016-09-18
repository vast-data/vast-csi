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
    virtual const char *get_name() { return Module::get_name(); }
    virtual ModuleId get_id() { return Module::get_id(); }

    virtual ControlObj *create_control_object(Control::IMDB *imdb)
    {
        return imdb->create<ControlObj>(P::GUID::create());
    }
};

ModuleFactoryImpl<TestModule, Control::TModuleObj> t;
ModuleFactoryImpl<P::PModule, Control::PModuleObj> p;
ModuleFactoryImpl<P::EModule, Control::EModuleObj> e;
ModuleFactoryImpl<Control::CModule, Control::CModuleObj> c;
ModuleFactoryImpl<BModule, Control::BModuleObj> b;
ModuleFactoryImpl<IModule, Control::IModuleObj> i;

ModuleFactory *factories[] = { &t, &p, &e, &c, &b, &i };

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
