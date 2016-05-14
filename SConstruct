import fnmatch
import os

def RGlob(path, pattern, ignore_dirs=[], ignore_files=[]):
   matches = []
   for root, dirnames, filenames in os.walk(path):
      if root in ignore_dirs:
         continue
      for filename in fnmatch.filter(filenames, pattern):
         filename = os.path.join(root, filename)
         if filename not in ignore_files:
            matches.append(filename)
   return matches

pre_sources = RGlob('src', '*.c', ['src/plasma/third_party/murmur3'], ['src/plasma/execution/main.c'])

VariantDir('build/src', 'src')
VariantDir('build/tests', 'tests')

env = Environment()
trace_builder = Builder(action='cat $SOURCE > $TARGET')
env.Append(BUILDERS={'SourceFile': trace_builder})

env['ENV']['TERM'] = os.environ['TERM'] # enable terminal colors in clang

env.Replace(CC=ARGUMENTS.get('cc', 'clang'))
debug = ARGUMENTS.get('debug')
if debug is not None:
   env.Append(CPPDEFINES=['DEBUG'])
env.Append(CFLAGS=['-g',
                   '-std=gnu11',
                   '-O' + ARGUMENTS.get('O', '2'),
                   '-fno-omit-frame-pointer', # with -O2 this is required to be able to generate backtraces
                   '-Weverything' if env['CC'] == 'clang' else '-Wall',
                   '-Werror',
                   '-Wno-disabled-macro-expansion',
                   '-Wno-vla',
                   '-Wno-padded'])
env.Append(CPPPATH=['src', 'src/include'])

murmur_env = env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])
murmur = murmur_env.Object('build/src/plasma/third_party/murmur3/murmur3.c')

post_sources = [murmur]
for source_file in pre_sources:
   post_sources.append(env.Object(env.SourceFile('build/' + source_file.replace('.c', '.post.c'), source_file)))

tracemeta = env.Command('dist/tracemeta.json', pre_sources, "echo $SOURCES > $TARGET")
lib = env.Library(target='dist/orion', source=post_sources)
LIBS = ['unwind', 'config', 'pthread', lib]
env.Program(target='dist/env', source=['build/src/plasma/execution/main.c'], LIBS=LIBS)

def AddTest(target, source, env=env, wrap=[]):
    test_env = env.Clone()
    for func in wrap:
        test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = test_env.Program(target=target, source=source, LIBS=LIBS + ['cmocka'])
    test_env.Alias('test', test, test[0].abspath)

AddTest(target='dist/test_p_pool', source=[lib, 'build/tests/test_p_pool.c'])
AddTest(target='dist/test_p_dlist', source=[lib, 'build/tests/test_p_dlist.c'])
AddTest(target='dist/test_p_hash', env=murmur_env, source=[lib, 'build/tests/test_p_hash.c',
                                                           'build/src/plasma/third_party/murmur3/test.c'])
AddTest(target='dist/test_p_fiber', source=[lib, 'build/tests/test_p_fiber.c'])
AddTest(target='dist/test_time', source=[lib, 'build/tests/test_time.c'])
AddTest(target='dist/test_config', source=[lib, 'build/tests/test_config.c'])
AddTest(target='dist/test_env', source=[lib, 'build/tests/test_env.c'], wrap=['p_module_start', 'p_module_init'])
AddTest(target='dist/test_trace', source=[lib, 'build/tests/test_trace.c'])
env.AlwaysBuild('test')

env.Alias('docs', lib, 'doxygen')
env.AlwaysBuild('docs')
