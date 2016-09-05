#include "p_module.hpp"

namespace P {

void PModule::init(Silo *silo, Conf::ConfigSetting *module_setting)
{
    _agent.init(silo->get_id(), get_id());
}

}  // namespace P
