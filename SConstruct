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
env.Append(CPPPATH=['src/include'])

debug = ARGUMENTS.get('debug', 0)
if int(debug):
   env.Append(CFLAGS='-g')
else:
   env.Append(CFLAGS='-O2')
   env.Append(CFLAGS='-fno-omit-frame-pointer') # don't hurt backtraces

lib = env.Library(target='dist/orion', source=['build/src/plasma/memory/p_alloc.c',
                                               'build/src/plasma/memory/p_pool.c',
                                               'build/src/plasma/data/p_dlist.c'])

def AddTest(target, source):
    test = env.Program(target=target, source=source, LIBS=['cmocka', lib])
    env.Alias('test', test, test[0].abspath)

AddTest(target='dist/test_p_pool',
        source=[lib, 'build/tests/test_p_pool.c'])
AddTest(target='dist/test_p_dlist',
        source=[lib, 'build/tests/test_p_dlist.c'])
env.AlwaysBuild('test')

env.Alias('docs', lib, 'doxygen')
env.AlwaysBuild('docs')
