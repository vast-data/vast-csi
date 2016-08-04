/* Copyright (C) Vast Data Ltd. */
#include <gtest/gtest.h>

#include "plasma/fiber/scheduler.hpp"
#include "plasma/utils/time.hpp"

#include "plasma/fiber/sync/qlock.hpp"
#include "plasma/fiber/sync/rwlock.hpp"
#include "plasma/fiber/sync/sem.hpp"
#include "plasma/fiber/sync/event.hpp"
#include "plasma/fiber/sync/future.hpp"

#include "test_common_scheduler.hpp"

using namespace P::FiberSync;

static int qlock_step = 0;

static void first_qlocker(void *lock_arg)
{
    Qlock *lock = (Qlock*)lock_arg;

    EXPECT_EQ(0, qlock_step);
    qlock_step++;
    lock->lock(); // doesn't block
    EXPECT_EQ(1, qlock_step);
    qlock_step++;
    P::Fiber::yield();
    P::Fiber::yield();
    EXPECT_EQ(3, qlock_step);
    qlock_step++;
    lock->unlock();
}

static void second_qlocker(void *lock_arg)
{
    Qlock *lock = (Qlock*)lock_arg;

    EXPECT_EQ(2, qlock_step);
    qlock_step++;
    ASSERT_FALSE(lock->trylock());
    lock->lock(); // blocks!
    EXPECT_EQ(4, qlock_step);
    qlock_step++;
    lock->unlock();
}

TEST(TestFiberSync, test_qlock)
{
    Qlock lock;
    lock.init();

    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, first_qlocker, &lock, false);
    P::Fiber::init(FG_A, second_qlocker, &lock, false);


    P::Scheduler::run();

    lock.destroy();

    P::Scheduler::destroy();
}

static void dumb_qlocker(void *lock_arg)
{
    static int count = 0;
    Qlock *lock = (Qlock*)lock_arg;

    LOOP(100000, i) {
        lock->lock();
        count++;
        P::Fiber::yield();
        ASSERT_EQ(count, 1);
        count--;
        lock->unlock();
    }
}

TEST(TestFiberSync2, test_qlock)
{
    Qlock lock;
    lock.init();

    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, dumb_qlocker, &lock, false);
    P::Fiber::init(FG_A, dumb_qlocker, &lock, false);
    P::Fiber::init(FG_A, dumb_qlocker, &lock, false);
    P::Fiber::init(FG_A, dumb_qlocker, &lock, false);
    P::Fiber::init(FG_A, dumb_qlocker, &lock, false);

    P::Scheduler::run();

    lock.destroy();

    P::Scheduler::destroy();
}

static int rwlock_state = 0;

static void write_locker(void *lock_arg)
{
    RWlock *lock = (RWlock*)lock_arg;

    EXPECT_EQ(0, rwlock_state);
    rwlock_state++;

    lock->lock_write();

    EXPECT_EQ(1, rwlock_state);
    rwlock_state++;

    LOOP(100, i)
        P::Fiber::yield();

    lock->unlock();

    EXPECT_EQ(5, rwlock_state);
    rwlock_state++;
}

static void read_locker(void *lock_arg)
{
    RWlock *lock = (RWlock*)lock_arg;

    ASSERT_GE(rwlock_state, 1);
    ASSERT_LE(rwlock_state, 4); // 3 fibers
    rwlock_state++;

    lock->lock_read();

    ASSERT_GE(rwlock_state, 6);
    ASSERT_LE(rwlock_state, 8); // 3 fibers
    rwlock_state++;

    lock->unlock();
}

TEST(TestFiberSync, test_rwlock_barrier)
{
    RWlock lock;
    lock.init();

    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, write_locker, &lock, false);
    P::Fiber::init(FG_A, read_locker, &lock, false);
    P::Fiber::init(FG_A, read_locker, &lock, false);
    P::Fiber::init(FG_A, read_locker, &lock, false);

    P::Scheduler::run();

    lock.destroy();

    P::Scheduler::destroy();
}

static void simple_locker(void *lock_arg)
{
    RWlock *lock = (RWlock*)lock_arg;

    lock->lock_read();
    lock->unlock();
    lock->lock_write();
    lock->unlock();
}

TEST(TestFiberSync, test_rwlock_simple)
{
    RWlock lock;
    lock.init();

    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, simple_locker, &lock, false);

    P::Scheduler::run();

    lock.destroy();

    P::Scheduler::destroy();
}

static void sem_nonblocking(void *sem_arg)
{
    Sem *sem = (Sem*)sem_arg;

    ASSERT_TRUE(sem->trydec(2));
    ASSERT_FALSE(sem->trydec(1));
    sem->inc(2);
    ASSERT_TRUE(sem->trydec(2));
    ASSERT_FALSE(sem->trydec(1));
    sem->inc(2);
}

TEST(TestFiberSync, test_sem_nonblocking)
{
    Sem sem;
    sem.init(2);

    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, sem_nonblocking, &sem, false);

    P::Scheduler::run();

    sem.destroy();

    P::Scheduler::destroy();
}

static int sem_step = 0;
static bool sem_flag = false;

static void incrementer(void *sem_arg)
{
    Sem *sem = (Sem*)sem_arg;
    EXPECT_EQ(4, sem_step);
    sem_step++;

    sem->inc(2);

    LOOP(100, i)
        P::Fiber::yield();
    sem_flag = true;

    sem->inc(2);
}

static void decrementer(void *sem_arg)
{
    Sem *sem = (Sem*)sem_arg;

    ASSERT_GE(sem_step, 0);
    ASSERT_LE(sem_step, 3);
    sem_step++;
    sem->dec(1);

    if (sem_flag) {
        ASSERT_GE(sem_step, 7);
        ASSERT_LE(sem_step, 8);
        sem_step++;
    } else {
        ASSERT_GE(sem_step, 5);
        ASSERT_LE(sem_step, 6);
        sem_step++;
    }
}

TEST(TestFiberSync, test_sem_blocking)
{
    Sem sem;
    sem.init(0);

    P::Scheduler::init(&scheduler_config);

    LOOP(4, i) {
        P::Fiber::init(FG_A, decrementer, &sem, false);
    }

    P::Fiber::init(FG_A, incrementer, &sem, false);

    P::Scheduler::run();

    sem.destroy();

    P::Scheduler::destroy();
}

static int event_step = 0;

static void event_one_waiter(void *event_arg)
{
    Event *event = (Event*)event_arg;

    ASSERT_GE(event_step, 0);
    ASSERT_LE(event_step, 3);
    event_step++;

    event->wait();

    EXPECT_EQ(1, event_step % 2);
    event_step++;
}

static void event_one_setter(void *event_arg)
{
    Event *event = (Event*)event_arg;

    LOOP(4, i) {
        event->release_one();
        EXPECT_EQ(0, event_step % 2);
        event_step++;
        P::Fiber::yield();
    }
}

TEST(TestFiberSync, test_event_one)
{
    Event event;
    event.init();

    P::Scheduler::init(&scheduler_config);

    LOOP(4, i) {
        P::Fiber::init(FG_A, event_one_waiter, &event, false);
    }

    P::Fiber::init(FG_A, event_one_setter, &event, false);

    P::Scheduler::run();

    event.destroy();

    P::Scheduler::destroy();
}

static void event_all_waiter(void *event_arg)
{
    Event *event = (Event*)event_arg;

    event->wait();
}

static void event_all_setter(void *event_arg)
{
    Event *event = (Event*)event_arg;

    event->release_all();
}

TEST(TestFiberSync, test_event_all)
{
    Event event;
    event.init();

    P::Scheduler::init(&scheduler_config);

    LOOP(4, i) {
        P::Fiber::init(FG_A, event_all_waiter, &event, false);
    }

    P::Fiber::init(FG_A, event_all_setter, &event, false);

    P::Scheduler::run();

    event.destroy();

    P::Scheduler::destroy();
}

static void future_fast_setter(void *arg)
{
    Future *future = (Future*)arg;
    future->set();
}

static void future_slow_setter(void *arg)
{
    Future *future = (Future*)arg;

    P::TimerQueues::sleep(P::SleepInterval::SLEEP_100_MILLI);
    future->set();
}

static void future_main_setter(void *arg)
{
    Future *future = (Future*)arg;
    enum {
        child_future_wait_subset = 7,
        child_future_count = 10
    };
    Future *child_futures[child_future_count];
    LOOP(child_future_count, i) {
        child_futures[i] = new Future();
        child_futures[i]->init();
    }

    // launch setters for subset
    LOOP(child_future_wait_subset - 1, i) {
        P::Fiber::init(FG_C, future_fast_setter, child_futures[i], false);
    }

    Future::wait_any(child_futures, child_future_count);

    P::Fiber::init(FG_C, future_slow_setter, child_futures[child_future_count - 1], false);

    // wait for subset
    Future::wait_subset(child_futures, child_future_count, child_future_wait_subset);

    // launch setters for completions
    LOOP_FROM(child_future_wait_subset - 1, child_future_count - 1, i) {
        EXPECT_FALSE(child_futures[i]->is_set());
        P::Fiber::init(FG_C, future_fast_setter, child_futures[i], false);
    }

    Future::wait_all(child_futures, child_future_count);

    LOOP(child_future_count, i) {
        EXPECT_TRUE(child_futures[i]->is_set());
        child_futures[i]->destroy();
        delete child_futures[i];
    }

    future->set();
}

static void future_main_waiter(void *arg UNUSED)
{
    Future future;
    future.init();

    P::Fiber::init(FG_B, future_main_setter, &future, false);

    future.wait();
    future.destroy();
}

TEST(TestFiberSync, test_future)
{
    P::Scheduler::init(&scheduler_config);

    P::Fiber::init(FG_A, future_main_waiter, nullptr, false);

    uint64_t start =  P::get_time_nano();
    P::Scheduler::run();
    uint64_t duration = P::get_time_nano() - start;
    uint64_t duration_in_milli = NANO_TO_MILLI(duration);

    ASSERT_GE(duration_in_milli, 99);
    ASSERT_LE(duration_in_milli, 101);

    P::Scheduler::destroy();
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
