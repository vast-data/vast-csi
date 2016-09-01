#include "module_interface.hpp"
#include "e_module.hpp"
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
ModuleFactoryImpl<P::EModule> e;
ModuleFactoryImpl<IModule> i;

ModuleFactory *factories[] = { &t, &e, &i };

void register_modules()
{
    P::Env *env = P::Env::get();
    for (auto *factory : factories) {
        env->register_module(factory->get_id(), factory);
    }
}
