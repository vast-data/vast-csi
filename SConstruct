import os

VariantDir('build/src', 'src', duplicate=0)
VariantDir('build/tests', 'tests', duplicate=0)
env = Environment()
env['ENV']['TERM'] = os.environ['TERM'] # enable terminal colors in clang
env.Replace(CC='clang')
env.Append(CFLAGS='-std=c11')
env.Append(CFLAGS='-Weverything')
env.Append(CFLAGS='-Werror')
env.Append(CFLAGS='-Wno-padded')
env.Append(CPPPATH=['src'])

debug = ARGUMENTS.get('debug', 0)
if int(debug):
   env.Append(CFLAGS='-g')
else:
   env.Append(CFLAGS='-O2')

orion = env.Program(target='dist/orion',
                    source=['build/src/main.c',
                            'build/src/math.c',
                            'build/src/plasma/alloc.c',
                            'build/src/plasma/pool.c',
                            'build/src/plasma/dlist.c'])

def AddTest(target, source):
    test = env.Program(target=target, source=source, LIBS=['cmocka'])
    env.Alias('test', test, test[0].abspath)

AddTest(target='dist/test_math',
        source=['build/tests/test_math.c',
                'build/src/math.o'])
AddTest(target='dist/test_pool',
        source=['build/tests/test_pool.c',
                'build/src/plasma/alloc.o',
                'build/src/plasma/pool.o'])
AddTest(target='dist/test_dlist',
        source=['build/tests/test_dlist.c',
                'build/src/plasma/dlist.o',
                'build/src/plasma/alloc.o'])
env.AlwaysBuild('test')

env.Alias('docs', orion, 'doxygen')
env.AlwaysBuild('docs')
