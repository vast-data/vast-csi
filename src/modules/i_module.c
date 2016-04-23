#include <p.h>
#include "i_module.h"

typedef struct IModuleState IModuleState;
struct IModuleState {
    void *foo;
};

void *i_module_init(PSilo *silo)
{
    (void) silo;

    IModuleState *state = p_safe_malloc(sizeof(IModuleState));
    printf("I init\n");
    return state;
}

void i_module_start(void)
{
    printf("I start\n");
}
