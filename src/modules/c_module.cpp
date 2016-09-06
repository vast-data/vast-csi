/* Copyright (C) Vast Data Ltd. */
#include "c_module.hpp"

using namespace P;

namespace Control {

void CModule::init(Silo *silo, Conf::ConfigSetting *module_setting)
{
    _agent.init(silo->get_id(), get_id());
}

void CModule::start()
{

}

} // namespace Control
