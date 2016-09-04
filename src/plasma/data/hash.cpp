/* Copyright (C) Vast Data Ltd. */
#include "plasma/third_party/murmur3/murmur3.h"
#include "hash.hpp"
#include "plasma/utils/math.hpp"

#define SEED 123

namespace P {

void Hash::init_custom(size_t n_buckets, Index n_values, MatchFunc match_func, void *match_arg,
                       HashFunc hash_func)
{
    ASSERT(is_power_of_two(n_buckets), "n_buckets should be power of 2");
    _match_func = match_func;
    _match_arg = match_arg;
    _hash_func = hash_func;
    _n_buckets = n_buckets;
    _values.init(n_values);
    _buckets = new DList::Anchor[n_buckets];
    LOOP(n_buckets, i) {
        _buckets[i].init();
    }
}

size_t default_hash_func(void *key, size_t length)
{
    uint32_t murmur_hash;
    MurmurHash3_x86_32(key, (int) length, SEED, &murmur_hash);
    return murmur_hash;
}

void Hash::init(size_t n_buckets, P::Index n_values, MatchFunc match_func, void *match_arg)
{
    Hash::init_custom(n_buckets, n_values, match_func, match_arg, default_hash_func);
}

bool Hash::set(void *key, size_t length, P::Index value)
{
    DList list;
    list.init(get_bucket(key, length), &_values);
    ITER_EACH(&list, i)
    {
        if (_match_func(_match_arg, i, key, length)) {
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
    DList list;
    list.init(get_bucket(key, length), &_values);
    ITER_EACH(&list, i)
    {
        if (_match_func(_match_arg, i, key, length)) {
            return i;
        }
    }
    return P::INVALID_INDEX;
}

bool Hash::remove(void *key, size_t length)
{
    DList list;
    list.init(get_bucket(key, length), &_values);
    ITER_EACH(&list, i)
    {
        if (_match_func(_match_arg, i, key, length)) {
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
