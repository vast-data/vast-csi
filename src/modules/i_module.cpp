#include <stdio.h>
#include "i_module.hpp"

using namespace P::Conf;
using P::Silo;

void IModule::init(Silo *silo, ConfigSetting *setting)
{
    (void) silo;
    (void) setting;
}

void IModule::start()
{

}
