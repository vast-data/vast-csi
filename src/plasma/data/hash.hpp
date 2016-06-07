/* Copyright (C) Vast Data Ltd. */

/*!
 * \file hash.hpp
 * \brief A hash table.
 *
 * This hash table maps any key (variable-sized buffer) to an index.
 *
 * Future considerations:
 * 1. Add thread safety.
 */

#pragma once


#include <stdbool.h>
#include <stddef.h>
#include "../utils/types.hpp"
#include "dlist.hpp"

namespace P {

class Hash {
public:

    typedef bool (*PHashMatchFunc)(void *match_arg, P::Index value, void *key, size_t length);
    typedef size_t (*PHashKeyToBucket)(Hash *hash, void *key, size_t length);

    /*!
     * Initialize a hash table. Call destroy() to free allocated resources.
     *
     * \param n_buckets number of buckets. The value should be a power of 2.
     *        For consistent performance aim for n_buckets to be up to 75% of the expected keys.
     * \param n_values expected number of values in the hash.
     * \param match a match function that converts an index to a key and compares with the given key.
     * \param match_arg a parameter to pass over to match.
     * \return a pointer to a heap allocated hash table.
     */
    void init(size_t n_buckets, P::Index n_values, PHashMatchFunc match, void *match_arg);

    /*!
     * Initialize a hash table with a custom hash function.
     * Gets the same parameters as init() with an extra key_to_bucket parameter.
     *
     * \param key_to_bucket a function that gets a key and returns its respective bucket.
     */
    void init_custom(size_t n_buckets, P::Index n_values, PHashMatchFunc match,
                     void *match_arg, PHashKeyToBucket key_to_bucket);

    /*!
     * Set a key+value pair.
     *
     * \param key a pointer to a buffer.
     * \param length size of the buffer in bytes.
     * \return a boolean indicating if the value was inserted.
     */
    bool set(void *key, size_t length, P::Index value);

    /*!
     * Get the value of a key in the hash.
     *
     * \param key a pointer to a buffer.
     * \param length size of the buffer in bytes.
     * \return the index if the key exists, otherwise P_INVALID_INDEX.
     */
    P::Index get(void *key, size_t length);

    /*!
     * Remove a key from the hash.
     *
     * \return a boolean indicating whether the key existed or not.
     */
    bool remove(void *key, size_t length);

    void destroy();

    size_t get_n_buckets() const { return _n_buckets; }

private:

    static size_t default_key_to_bucket(Hash *hash, void *key, size_t length);

private:
    size_t _n_buckets;
    P::DList::Anchor *_buckets;
    P::DList::Pool _values;
    PHashMatchFunc _match;
    void *_match_arg;
    PHashKeyToBucket _key_to_bucket;
};

}