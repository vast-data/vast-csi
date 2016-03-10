VariantDir('build/src', 'src', duplicate=0)
VariantDir('build/tests', 'tests', duplicate=0)
env = Environment()
env.Replace(CC='clang')
env.Append(CFLAGS='-g')
env.Append(CCFLAGS='-Weverything')
env.Append(CPPPATH=['src'])

orion = env.Program(target='dist/orion',
                    source=['build/src/main.c'])

def AddTest(target, source):
    test = env.Program(target=target, source=source, LIBS=['cmocka'])
    env.Alias('test', test, test[0].abspath)

AddTest(target='dist/test_math',
        source=['build/tests/test_math.c',
                'build/src/math.o'])
env.AlwaysBuild('test')
