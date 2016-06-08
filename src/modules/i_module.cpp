#include <stdio.h>
#include "i_module.hpp"

using namespace P::Conf;
using P::Silo;

typedef struct IModuleState IModuleState;
struct IModuleState {
    void *foo;
};

void *IModule::init(Silo *silo, ConfigSetting *setting)
{
    (void) silo;
    (void) setting;

    printf("IModule::init\n");
    IModuleState *state = new IModuleState;

    return state;
}

void IModule::start(void)
{
    printf("IModule::start\n");
}
