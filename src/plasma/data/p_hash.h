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

typedef struct p_hash p_hash;

typedef bool (*p_hash_match_func)(void *match_arg, p_index value, void *key, size_t length);
typedef size_t (*p_hash_key_to_bucket)(p_hash *hash, void *key, size_t length);

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
p_hash *p_hash_init(size_t n_buckets, p_index n_values, p_hash_match_func match, void *match_arg);

/*!
 * Initialize a hash table with a custom hash function.
 * Gets the same parameters as p_hash_init() with an extra key_to_bucket parameter.
 *
 * \param key_to_bucket a function that gets a key and returns its respective bucket.
 */
p_hash *p_hash_init_custom(size_t n_buckets, p_index n_values, p_hash_match_func match, void *match_arg,
                           p_hash_key_to_bucket key_to_bucket);

/*!
 * Set a key+value pair.
 *
 * \param key a pointer to a buffer.
 * \param length size of the buffer in bytes.
 * \return a boolean indicating if the value was inserted.
 */
bool p_hash_set(p_hash *hash, void *key, size_t length, p_index value);

/*!
 * Get the value of a key in the hash.
 *
 * \param key a pointer to a buffer.
 * \param length size of the buffer in bytes.
 * \return the index if the key exists, otherwise P_INVALID_INDEX.
 */
p_index p_hash_get(p_hash *hash, void *key, size_t length);

/*!
 * Remove a key from the hash.
 *
 * \return a boolean indicating whether the key existed or not.
 */
bool p_hash_remove(p_hash *hash, void *key, size_t length);

void p_hash_destroy(p_hash *hash);
