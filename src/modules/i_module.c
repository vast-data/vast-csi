#include <p.h>
#include "i_module.h"

typedef struct IModuleState IModuleState;
struct IModuleState {
    void *foo;
};

void *i_module_init(PSilo *silo, PConfigSetting *setting)
{
    (void) silo;
    (void) setting;

    IModuleState *state = p_safe_malloc(sizeof(IModuleState));

    return state;
}

void i_module_start(void)
{

}
