/* Copyright (C) Vast Data Ltd. */
#include "plasma/third_party/murmur3/murmur3.h"
#include "hash.hpp"
#include "plasma/utils/math.hpp"

#define SEED 123

namespace P {

void Hash::init_custom(size_t n_buckets, P::Index n_values, PHashMatchFunc match, void *match_arg,
                        PHashKeyToBucket key_to_bucket)
{
    ASSERT(is_power_of_two(n_buckets), "n_buckets should be power of 2");
    _match = match;
    _match_arg = match_arg;
    _key_to_bucket = key_to_bucket;
    _n_buckets = n_buckets;
    _values.init(n_values);
    _buckets = new DList::Anchor[n_buckets];
    LOOP(n_buckets, i) {
        _buckets[i].init();
    }
}

size_t Hash::default_key_to_bucket(Hash *hash, void *key, size_t length)
{
    uint32_t murmur_hash;
    MurmurHash3_x86_32(key, (int) length, SEED, &murmur_hash);
    return murmur_hash & (hash->get_n_buckets() - 1);
}

void Hash::init(size_t n_buckets, P::Index n_values, PHashMatchFunc match, void *match_arg)
{
    Hash::init_custom(n_buckets, n_values, match, match_arg, default_key_to_bucket);
}

bool Hash::set(void *key, size_t length, P::Index value)
{
    size_t bucket_index = _key_to_bucket(this, key, length);
    DList list;
    list.init(&_buckets[bucket_index], &_values);
    ITER_EACH(&list, i)
    {
        if (_match(_match_arg, i, key, length)) {
            if (i == value) {
                return false;
            } else {
                list.remove(i);
                break;
            }
        }
    }
    list.insert(value);
    return true;
}

P::Index Hash::get(void *key, size_t length)
{
    DList::Anchor *bucket = &_buckets[_key_to_bucket(this, key, length)];
    DList list;
    list.init(bucket, &_values);
    ITER_EACH(&list, i)
    {
        if (_match(_match_arg, i, key, length)) {
            return i;
        }
    }
    return P::INVALID_INDEX;
}

bool Hash::remove(void *key, size_t length)
{
    size_t bucket_index = _key_to_bucket(this, key, length);
    DList::Anchor *bucket = &_buckets[bucket_index];
    DList list;
    list.init(bucket, &_values);
    ITER_EACH(&list, i)
    {
        if (_match(_match_arg, i, key, length)) {
            list.remove(i);
            return true;
        }
    }
    return false;
}

void Hash::destroy()
{
    _values.destroy();
    delete[] _buckets;
}

}
