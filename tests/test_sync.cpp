/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "plasma/utils/time.hpp"
#include "plasma/sync/rw_spinlock.hpp"
#include "plasma/sync/spin_lock.hpp"

using namespace P::Sync;

static const size_t spinlock_iterations = 100000;
static const size_t rwspinlock_rlock_iterations = 100000;
static const size_t rwspinlock_wlock_iterations = 100000;

static void* locker(void* arg)
{
    SpinLock* lock = (SpinLock*)arg;
    LOOP(spinlock_iterations, i) {
        lock->lock();
        lock->unlock();
    }
    return nullptr;
}

TEST(TestSync, test_spin)
{
    SpinLock lock;
    lock.init();

    pthread_t lockers[10];

    int ret;
    LOOP(NUM_ELEMENTS(lockers), i) {
        ret = pthread_create(&lockers[i], nullptr, locker, &lock);
        ASSERT_TRUE(ret == 0);
    }

    LOOP(NUM_ELEMENTS(lockers), i) {
        ret = pthread_join(lockers[i], nullptr);
        ASSERT_TRUE(ret == 0);
    }

    lock.destroy();
}

TEST(TestSync, test_spin_perf)
{
    SpinLock lock;
    lock.init();

    uint64_t start = P::get_time_nano();
    locker(&lock);
    uint64_t interval = P::get_time_nano() - start;
    printf("Performed %lu lock/unlock operations in %lums. each took %luns\n",
            spinlock_iterations, NANO_TO_MILLI(interval), interval/spinlock_iterations);

    lock.destroy();
}

static void* rlocker(void* arg)
{
    RWSpinLock* lock = (RWSpinLock*)arg;
    LOOP(rwspinlock_rlock_iterations, i) {
        if(!lock->rtrylock()) {
            lock->rlock();
        }
        lock->runlock();
    }

    return nullptr;
}

static void* wlocker(void* arg)
{
    RWSpinLock* lock = (RWSpinLock*)arg;
    LOOP(rwspinlock_wlock_iterations, i) {
        if(!lock->wtrylock()) {
            lock->wlock();
        }
        lock->wunlock();
    }

    return nullptr;
}

TEST(TestSync, test_rwspin)
{
    RWSpinLock lock;
    lock.init();

    pthread_t rlockers[10];
    pthread_t wlockers[10];

    int ret;

    LOOP(NUM_ELEMENTS(rlockers), i) {
        ret = pthread_create(&rlockers[i], nullptr, rlocker, &lock);
        ASSERT_TRUE(ret == 0);
    }

    LOOP(NUM_ELEMENTS(wlockers), i) {
        ret = pthread_create(&wlockers[i], nullptr, wlocker, &lock);
        ASSERT_TRUE(ret == 0);
    }

    LOOP(NUM_ELEMENTS(rlockers), i) {
        ret = pthread_join(rlockers[i], nullptr);
        ASSERT_TRUE(ret == 0);
    }

    LOOP(NUM_ELEMENTS(wlockers), i) {
        ret = pthread_join(wlockers[i], nullptr);
        ASSERT_TRUE(ret == 0);
    }

    lock.destroy();
}

TEST(TestSync, test_rwspin_perf)
{
    RWSpinLock lock;
    lock.init();

    uint64_t start = P::get_time_nano();
    rlocker(&lock);
    uint64_t interval = P::get_time_nano() - start;
    printf("Performed %lu rlock/runlock operations in %lums. each took %luns\n",
            rwspinlock_rlock_iterations, NANO_TO_MILLI(interval), interval/rwspinlock_rlock_iterations);

    start = P::get_time_nano();
    wlocker(&lock);
    interval = P::get_time_nano() - start;
    printf("Performed %lu wlock/wunlock operations in %lums. each took %luns\n",
            rwspinlock_wlock_iterations, NANO_TO_MILLI(interval), interval/rwspinlock_wlock_iterations);

    lock.destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
