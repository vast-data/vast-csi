import fnmatch
import os

DEFAULT_COMPILER = 'clang'
DEFAULT_OPTIMIZATION_LEVEL = '2'
DEFAULT_BUILD_DIR = 'build'

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

sources = [DEFAULT_BUILD_DIR + '/' + i for i in RGlob('src', '*.c', ['src/plasma/third_party/murmur3'], ['src/plasma/execution/main.c'])]

VariantDir(DEFAULT_BUILD_DIR + '/src', 'src')
VariantDir(DEFAULT_BUILD_DIR + '/tests', 'tests')

vars = Variables(None, ARGUMENTS)
vars.Add(BoolVariable('debug', 'Set debug to 1 to compile a debug version (defines the DEBUG macro)', False))
vars.Add(EnumVariable('cc', 'A c compiler', DEFAULT_COMPILER, allowed_values=('clang', 'gcc')))
vars.Add('O', 'Optimization level', DEFAULT_OPTIMIZATION_LEVEL)

env = Environment(variables=vars)
help_text = """
Targets
-------
Available targets:
1. <none> - when running scons with no targets all executables are built.
2. test - builds all test executables and invokes them.
3. docs - builds the documentation. The result is located at docs/html/index.html.

Parameters
----------
Parameters are passed as key=value. For example: scons debug=yes.

""" + vars.GenerateHelpText(env)
Help(help_text)

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
                   '-Wno-gnu-zero-variadic-macro-arguments',
                   '-Wno-vla',
                   '-Wno-padded'])
env.Append(CPPPATH=['src', 'src/include'])

murmur_env = env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])
murmur = murmur_env.Object(DEFAULT_BUILD_DIR + '/src/plasma/third_party/murmur3/murmur3.c')

sources.append(murmur)

lib = env.Library(target='dist/orion', source=sources)
LIBS = ['unwind', 'config', 'pthread', lib]
env.Program(target='dist/env', source=[DEFAULT_BUILD_DIR + '/src/plasma/execution/main.c'], LIBS=LIBS)

def AddTest(target, source, env=env, wrap=[]):
    test_env = env.Clone()
    for func in wrap:
        test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = test_env.Program(target=target, source=source, LIBS=LIBS + ['cmocka'])
    test_env.Alias('test', test, test[0].abspath)

AddTest(target='dist/tests/test_p_pool', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_p_pool.c'])
AddTest(target='dist/tests/test_p_dlist', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_p_dlist.c'])
AddTest(target='dist/tests/test_p_hash', env=murmur_env, source=[lib, DEFAULT_BUILD_DIR + '/tests/test_p_hash.c',
                                                           DEFAULT_BUILD_DIR + '/src/plasma/third_party/murmur3/test.c'])
AddTest(target='dist/tests/test_p_fiber', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_p_fiber.c'])
AddTest(target='dist/tests/test_time', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_time.c'])
AddTest(target='dist/tests/test_config', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_config.c'])
AddTest(target='dist/tests/test_env', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_env.c'], wrap=['p_module_start', 'p_module_init'])
AddTest(target='dist/tests/test_trace', source=[lib, DEFAULT_BUILD_DIR + '/tests/test_trace.c'])
env.AlwaysBuild('test')

env.Alias('docs', lib, 'doxygen')
env.AlwaysBuild('docs')
