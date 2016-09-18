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


#include "plasma/utils/types.hpp"
#include "dlist.hpp"

namespace P {

class Hash {
public:

    typedef bool (*MatchFunc)(void *match_arg, P::Index value, void *key, size_t length);
    typedef size_t (*HashFunc)(void *key, size_t length);

    /*!
     * Initialize a hash table. Call destroy() to free allocated resources.
     *
     * \param n_buckets number of buckets. The value should be a power of 2.
     *        For consistent performance aim for n_buckets to be up to 75% of the expected keys.
     * \param n_values expected number of values in the hash.
     * \param match_func a match function that converts an index to a key and compares with the given key.
     * \param match_arg a parameter to pass over to match.
     */
    void init(size_t n_buckets, Index n_values, MatchFunc match_func, void *match_arg);

    /*!
     * Initialize a hash table with a custom hash function.
     * Gets the same parameters as init() with an extra key_to_bucket parameter.
     *
     * \param hash_func a function that gets a key and returns a hash.
     */
    void init_custom(size_t n_buckets, Index n_values, MatchFunc match_func, void *match_arg, HashFunc hash_func);

    /*!
     * Set a key+value pair.
     *
     * \param key a pointer to a buffer.
     * \param length size of the buffer in bytes.
     * \return a boolean indicating if the value was inserted.
     */
    bool set(void *key, size_t length, Index value);

    /*!
     * Get the value of a key in the hash.
     *
     * \param key a pointer to a buffer.
     * \param length size of the buffer in bytes.
     * \return the index if the key exists, otherwise P_INVALID_INDEX.
     */
    Index get(void *key, size_t length);

    /*!
     * Remove a key from the hash.
     *
     * \return a boolean indicating whether the key existed or not.
     */
    bool remove(void *key, size_t length);

    void destroy();

    size_t get_n_buckets() const { return _n_buckets; }

private:
    DList::Anchor *get_bucket(void *key, size_t length) { return &_buckets[_hash_func(key, length) & (_n_buckets - 1)]; }

    size_t _n_buckets;
    DList::Anchor *_buckets;
    DList::Pool _values;
    MatchFunc _match_func;
    void *_match_arg;
    HashFunc _hash_func;
};

}
