VariantDir('build/src', 'src', duplicate=0)
VariantDir('build/tests', 'tests', duplicate=0)
env = Environment()
env.Replace(CC='clang')
env.Append(CCFLAGS='-Weverything')
env.Append(CPPPATH=['src'])

env.Program(target='dist/orion',
            source=['build/src/main.c'])
env.Program(target='dist/test_math',
            source=['build/src/math.c', 'build/tests/test_math.c'],
            LIBS=['cmocka'])
