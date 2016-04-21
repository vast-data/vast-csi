/* Copyright (C) Vast Data Ltd. */

/*!
 * \file p_hash.h
 * \brief A hash table.
 *
 * This hash table maps any key (variable-sized buffer) to an index.
 *
 * Future considerations:
 * 1. Add thread safety.
 */

#pragma once

#include <p.h>

typedef struct PHash PHash;

typedef bool (*PHashMatchFunc)(void *match_arg, PIndex value, void *key, size_t length);
typedef size_t (*PHashKeyToBucket)(PHash *hash, void *key, size_t length);

/*!
 * Initialize a hash table. Call p_hash_destroy() to free allocated resources.
 *
 * \param n_buckets number of buckets. The value should be a power of 2.
 *        For consistent performance aim for n_buckets to be up to 75% of the expected keys.
 * \param n_values expected number of values in the hash.
 * \param match a match function that converts an index to a key and compares with the given key.
 * \param match_arg a parameter to pass over to match.
 * \return a pointer to a heap allocated hash table.
 */
PHash *p_hash_init(size_t n_buckets, PIndex n_values, PHashMatchFunc match, void *match_arg);

/*!
 * Initialize a hash table with a custom hash function.
 * Gets the same parameters as p_hash_init() with an extra key_to_bucket parameter.
 *
 * \param key_to_bucket a function that gets a key and returns its respective bucket.
 */
PHash *p_hash_init_custom(size_t n_buckets, PIndex n_values, PHashMatchFunc match,
                          void *match_arg, PHashKeyToBucket key_to_bucket);

/*!
 * Set a key+value pair.
 *
 * \param key a pointer to a buffer.
 * \param length size of the buffer in bytes.
 * \return a boolean indicating if the value was inserted.
 */
bool p_hash_set(PHash *hash, void *key, size_t length, PIndex value);

/*!
 * Get the value of a key in the hash.
 *
 * \param key a pointer to a buffer.
 * \param length size of the buffer in bytes.
 * \return the index if the key exists, otherwise P_INVALID_INDEX.
 */
PIndex p_hash_get(PHash *hash, void *key, size_t length);

/*!
 * Remove a key from the hash.
 *
 * \return a boolean indicating whether the key existed or not.
 */
bool p_hash_remove(PHash *hash, void *key, size_t length);

void p_hash_destroy(PHash *hash);
