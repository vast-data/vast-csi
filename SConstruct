VariantDir('build', 'src', duplicate=0)
env = Environment()
env.Replace(CC='clang')
env.Append(CCFLAGS='-Weverything')
env.Append(CPPPATH=['src'])

env.Program(target='dist/orion',
            source=['build/main.c'])
env.Program(target='dist/test_math',
            source=['build/math.c', 'tests/test_math.c'],
            LIBS=['cmocka'])
