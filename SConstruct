import os

VariantDir('build/src', 'src', duplicate=0)
VariantDir('build/tests', 'tests', duplicate=0)
env = Environment()
env['ENV']['TERM'] = os.environ['TERM'] # enable terminal colors in clang

env.Replace(CC=ARGUMENTS.get('cc', 'clang'))
env.Append(CFLAGS=['-g',
                   '-std=gnu11',
                   '-O' + ARGUMENTS.get('O', '2'),
                   '-fno-omit-frame-pointer', # with -O2 this is required to be able to generate backtraces
                   '-Weverything' if env['CC'] == 'clang' else '-Wall',
                   '-Werror',
                   '-Wno-disabled-macro-expansion',
                   '-Wno-vla',
                   '-Wno-padded'])
env.Append(CPPPATH=['src',
                    'src/include'])

murmur_env = env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])
murmur = murmur_env.Object('build/src/plasma/third_party/murmur3/murmur3.c')

lib = env.Library(target='dist/orion',
                  source=['build/src/defs.c',
                          'build/src/modules/p_module.c',
                          'build/src/modules/i_module.c',
                          'build/src/plasma/time.c',
                          'build/src/plasma/utils.c',
                          'build/src/plasma/backtrace.c',
                          'build/src/plasma/memory/p_alloc.c',
                          'build/src/plasma/memory/p_pool.c',
                          'build/src/plasma/data/p_ilist.c',
                          'build/src/plasma/data/p_dlist.c',
                          'build/src/plasma/data/p_hash.c',
                          'build/src/plasma/fiber/p_fiber.c',
                          'build/src/plasma/fiber/p_scheduler.c',
                          'build/src/plasma/fiber/p_sleep.c',
                          'build/src/plasma/sync/p_spin_lock.c',
                          'build/src/plasma/sync/p_qlock.c',
                          'build/src/plasma/sync/p_rwlock.c',
                          'build/src/plasma/sync/p_sem.c',
                          'build/src/plasma/execution/p_config.c',
                          'build/src/plasma/execution/p_silo.c',
                          'build/src/plasma/execution/p_env.c',
                          murmur])
LIBS = ['unwind', 'config', 'pthread', lib]

env.Program(target='dist/env', source=['build/src/plasma/execution/main.c'], LIBS=LIBS)

def AddTest(target, source, env=env, wrap=[]):
    test_env = env.Clone()
    for func in wrap:
        test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = test_env.Program(target=target, source=source, LIBS=LIBS + ['cmocka'])
    test_env.Alias('test', test, test[0].abspath)

AddTest(target='dist/test_p_pool',
        source=[lib, 'build/tests/test_p_pool.c'])
AddTest(target='dist/test_p_dlist',
        source=[lib, 'build/tests/test_p_dlist.c'])
AddTest(target='dist/test_p_hash',
        source=[lib, 'build/tests/test_p_hash.c',
                'build/src/plasma/third_party/murmur3/test.c'],
        env=murmur_env)
AddTest(target='dist/test_p_fiber',
        source=[lib,
                'build/tests/test_p_fiber.c'])
AddTest(target='dist/test_time',
        source=[lib, 'build/tests/test_time.c'])
AddTest(target='dist/test_config',
        source=[lib, 'build/tests/test_config.c'])
AddTest(target='dist/test_env',
        source=[lib, 'build/tests/test_env.c'],
        wrap=['p_module_start', 'p_module_init'])
env.AlwaysBuild('test')

env.Alias('docs', lib, 'doxygen')
env.AlwaysBuild('docs')
