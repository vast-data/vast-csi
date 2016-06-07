#include "i_module.hpp"

using namespace P::Conf;
using P::Silo;

typedef struct IModuleState IModuleState;
struct IModuleState {
    void *foo;
};

void *i_module_init(Silo *silo, ConfigSetting *setting)
{
    (void) silo;
    (void) setting;

    printf("i_module_init\n");
    IModuleState *state = new IModuleState;

    return state;
}

void i_module_start(void)
{
    printf("i_module_start\n");
}
