#include "module_interface.hpp"
#include "p_module.hpp"
#include "i_module.hpp"
#include "../tests/test_module.hpp"
#include "plasma/execution/env.hpp"

template <class T>
class ModuleFactoryImpl : public ModuleFactory {
    virtual ModuleInterface *create() { return new T(); }
    virtual const char *get_name() { return T::get_name(); }
    virtual ModuleId get_id() { return T::get_id(); }
};

ModuleFactoryImpl<TestModule> t;
ModuleFactoryImpl<PModule> p;
ModuleFactoryImpl<IModule> i;

ModuleFactory *factories[] = { &t, &p, &i };

void register_modules()
{
    P::Env *env = P::Env::get();
    for (auto *factory : factories) {
        env->register_module(factory->get_id(), factory);
    }
}

const char *get_module_name(ModuleId module_id)
{
    for (auto *factory : factories)
        if (factory->get_id() == module_id)
            return factory->get_name();
    PANIC("ModuleId " << (int)module_id << " not found");
}

ModuleId get_module_id(const char *module_name)
{
    for (auto *factory : factories) {
        if (strcmp(factory->get_name(), module_name) == 0) {
            return factory->get_id();
        }
    }
    PANIC("Module " << module_name << " not found");
}

