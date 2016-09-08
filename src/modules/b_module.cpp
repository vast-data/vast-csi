#include "b_module.hpp"
#include "plasma/io/io_provider.hpp"
#include "plasma/fiber/fiber.hpp"
#include "plasma/utils/types.hpp"
#include "plasma/internal.hpp"
#include "globals.hpp"

using namespace P::Conf;

void BModule::init(P::Silo *silo, ConfigSetting *module_setting)
{
    ConfigSetting *lock_manager_setting = conf_setting_lookup_required(module_setting, "components.lock_manager");
    _agent.init(silo->get_id(), get_id());
    _lock_manager_server.init(silo->get_id(), ModuleId::B, lock_manager_setting);
}

void BModule::start()
{
}

