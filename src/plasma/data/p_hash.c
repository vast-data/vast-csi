/* Copyright (C) Vast Data Ltd. */
#include <p.h>
#include "plasma/third_party/murmur3/murmur3.h"

#define SEED 123

struct p_hash {
    size_t n_buckets;
    p_dlist_anchor *buckets;
    p_dlist *values;
    p_hash_match_func match;
    void *match_arg;
    p_hash_key_to_bucket key_to_bucket;
};

p_hash *p_hash_init_custom(size_t n_buckets, p_index n_values, p_hash_match_func match, void *match_arg,
                           p_hash_key_to_bucket key_to_bucket)
{
    P_ASSERT(p_is_power_of_two(n_buckets));
    p_hash *hash = p_safe_malloc(sizeof(p_hash));
    hash->match = match;
    hash->match_arg = match_arg;
    hash->key_to_bucket = key_to_bucket;
    hash->n_buckets = n_buckets;
    hash->buckets = p_safe_malloc(sizeof(p_dlist_anchor) * n_buckets);
    hash->values = p_dlist_init(n_values);
    LOOP(n_buckets, i)
        hash->buckets[i] = P_DLIST_ANCHOR_INIT;
    return hash;
}

static size_t default_key_to_bucket(p_hash *hash, void *key, size_t length)
{
    uint32_t murmur_hash;
    MurmurHash3_x86_32(key, (int) length, SEED, &murmur_hash);
    return murmur_hash & (hash->n_buckets - 1);
}

p_hash *p_hash_init(size_t n_buckets, p_index n_values, p_hash_match_func match, void *match_arg)
{
    return p_hash_init_custom(n_buckets, n_values, match, match_arg, default_key_to_bucket);
}

bool p_hash_set(p_hash *hash, void *key, size_t length, p_index value)
{
    size_t bucket_index = hash->key_to_bucket(hash, key, length);
    p_dlist_anchor bucket = hash->buckets[bucket_index];
    P_DLIST_EACH(hash->values, bucket, i) {
        if (hash->match(hash->match_arg, i, key, length)) {
            if (i == value) {
                return false;
            } else {
                p_dlist_remove(hash->values, &bucket, i);
                break;
            }
        }
    }
    p_dlist_insert(hash->values, &bucket, value);
    hash->buckets[bucket_index] = bucket;
    return true;
}

p_index p_hash_get(p_hash *hash, void *key, size_t length)
{
    p_dlist_anchor bucket = hash->buckets[hash->key_to_bucket(hash, key, length)];
    P_DLIST_EACH(hash->values, bucket, i) {
        if (hash->match(hash->match_arg, i, key, length)) {
            return i;
        }
    }
    return P_INVALID_INDEX;
}

bool p_hash_remove(p_hash *hash, void *key, size_t length)
{
    size_t bucket_index = hash->key_to_bucket(hash, key, length);
    p_dlist_anchor bucket = hash->buckets[bucket_index];
    P_DLIST_EACH(hash->values, bucket, i) {
        if (hash->match(hash->match_arg, i, key, length)) {
            p_dlist_remove(hash->values, &bucket, i);
            hash->buckets[bucket_index] = bucket;
            return true;
        }
    }
    return false;
}

void p_hash_destroy(p_hash *hash)
{
    p_free(hash->buckets);
    p_free(hash);
}
