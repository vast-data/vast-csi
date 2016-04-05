import os

VariantDir('build/src', 'src', duplicate=0)
VariantDir('build/tests', 'tests', duplicate=0)
env = Environment()
env['ENV']['TERM'] = os.environ['TERM'] # enable terminal colors in clang

env.Replace(CC=ARGUMENTS.get('cc', 'clang'))
env.Append(CFLAGS=['-std=c11',
                   '-Weverything' if env['CC'] == 'clang' else '-Wall',
                   '-Werror',
                   '-Wno-padded'])
env.Append(CPPPATH=['src',
                    'src/include'])

debug = ARGUMENTS.get('debug', 0)
if int(debug):
   env.Append(CFLAGS='-g')
else:
   env.Append(CFLAGS='-O2')
   env.Append(CFLAGS='-fno-omit-frame-pointer') # required for debugging and generating backtraces

murmur_env = env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])
murmur = murmur_env.Object('build/src/plasma/third_party/murmur3/murmur3.c')

lib = env.Library(target='dist/orion',
                  source=['build/src/plasma/utils.c',
                          'build/src/plasma/memory/p_alloc.c',
                          'build/src/plasma/memory/p_pool.c',
                          'build/src/plasma/data/p_dlist.c',
                          'build/src/plasma/data/p_hash.c',
                          'build/src/plasma/fiber/p_fiber.c',
                          murmur])

def AddTest(target, source, env=env):
    test = env.Program(target=target, source=source, LIBS=['cmocka', lib])
    env.Alias('test', test, test[0].abspath)

AddTest(target='dist/test_p_pool',
        source=[lib, 'build/tests/test_p_pool.c'])
AddTest(target='dist/test_p_dlist',
        source=[lib, 'build/tests/test_p_dlist.c'])
AddTest(target='dist/test_p_hash',
        source=[lib, 'build/tests/test_p_hash.c',
                'build/src/plasma/third_party/murmur3/test.c'],
        env=murmur_env)
AddTest(target='dist/test_p_fiber',
        source=[lib, 'build/tests/test_p_fiber.c'])
env.AlwaysBuild('test')

env.Alias('docs', lib, 'doxygen')
env.AlwaysBuild('docs')
