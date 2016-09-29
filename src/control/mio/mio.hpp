/* Copyright (C) Vast Data Ltd. */
#include "control/imdb/nvram.hpp"
#include "control/imdb/module.hpp"

namespace Control {

class MIOControl {
public:
    void init() {}
    void on_device_addition(BaseModuleLogic *module, NVRAM *nvram) {}
    void on_device_removal(BaseModuleLogic *module, NVRAM *nvram) {}
};

}
