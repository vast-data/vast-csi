/* Copyright (C) Vast Data Ltd. */

/*!
 * \file iterable.hpp
 * \brief An iterable collection abstract class.
 *
 * More information is available here: https://vastdata.atlassian.net/wiki/display/DEV/Data+Structures
 *
 */

#pragma once

#include "../utils/types.hpp"

namespace P {

class Iterable  {
public:
    /*!
     * Get the first list element index.
     */
    virtual Index get_first() = 0;

    /*!
     * Get the next collection element index.
     */
    virtual Index next(Index index) = 0;

    /*!
     * True if the item in index is the last in the collection.
     */
    virtual bool is_last(Index index) = 0;
};

/*!
 * Iterate over Iterable elements. It's forbidden to remove elements during iteration.
 * Example usage:
 *
\code{.c}
ITER_EACH(list, i) {
   printf("%d", i);
}
\endcode
 */
#define ITER_EACH(iterable, element) for (P::Index element = (iterable)->get_first();       \
                                       element != P::INVALID_INDEX;                             \
                                       element = (iterable)->is_last(element) ?               \
                                                 P::INVALID_INDEX : (iterable)->next(element))

/*!
 * This allows current item to be removed from the iterable in the body of the iteration
 * Example usage:
 *
\code{.c}
ITER_SAFE_EACH(iterable, i,
  printf("%d", i);
  iterable->remove(i);
)
\endcode
*/
#define ITER_SAFE_EACH(iterable, element, body)                                                               \
    for (P::Index element = (iterable)->get_first(); element != P::INVALID_INDEX;) {                          \
        P::Index next_element = (iterable)->is_last(element) ? P::INVALID_INDEX : (iterable)->next(element);\
        {body}                                                                                                  \
        element = next_element;                                                                                 \
  }

};
