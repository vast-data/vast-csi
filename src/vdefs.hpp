/* Copyright (C) Vast Data Ltd. */

/*!
 * \file defs.hpp
 * \brief Identifiers for various parts of software (fiber groups, components, etc')
 */
#pragma once

#include "plasma/utils/macros.hpp"

// TODO get rid of the  "_CPP" once the c code is gone
#define COMPONENT_LIST(X)                       \
    X(PLASMA),                                  \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES_CPP(COMPONENT_LIST,
                         ComponentId,
                         component_id_to_string,
                         component_id_from_string)

#define FIBER_GROUP_LIST(X)                  \
    X(P),                                    \
    X(P_IO_POLLING),                         \
    X(TEST),                                 \
    X(I_TEST),                               \
    X(COUNT)

DEFINE_LOOKUP_PROTOTYPES_CPP(FIBER_GROUP_LIST,
                         FiberGroupId,
                         fiber_group_id_to_string,
                         fiber_group_id_from_string)
