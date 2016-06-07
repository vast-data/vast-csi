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
env['ENV'].update(LC_ALL='en_US.UTF-8',
                  LANG='en_US.UTF-8',
                  LANGUAGE='en_US.UTF-8')

optimizations = ARGUMENTS.get('O', '2')
debug = ARGUMENTS.get('debug')
if debug is not None:
    optimizations = '0'
    env.Append(CPPDEFINES=['DEBUG'])

compiler = ARGUMENTS.get('cc', 'clang')
if compiler == 'clang':
    env.Replace(CC=compiler, CXX=compiler + '++')
    env.Append(CFLAGS=['-Weverything',
                       '-Wno-disabled-macro-expansion',
                       '-Wno-gnu-zero-variadic-macro-arguments'])
else:
    assert compiler == 'gcc'
    env.Replace(CC='/opt/rh/devtoolset-3/root/usr/bin/gcc',
                CXX='g++')
    env.Append(CFLAGS=['-Wall'])

env.Append(CPPFLAGS=['-g',
                     '-O' + optimizations,
                     '-fno-omit-frame-pointer', # with -O2 this is required to be able to generate backtraces
                     '-Werror',
                     '-Wno-vla',
                     '-Wno-padded',
                     '-Wno-cast-align'])
env.Append(CPPPATH=['src', 'src/include'])
env.Append(LINKFLAGS=['-pthread'])
env.Append(LIBS=['unwind', 'config', 'libaio'])

# ----- C Environment ----- #

c_env = env.Clone()
c_env.Append(CFLAGS='-std=gnu11')

csources = [DEFAULT_BUILD_DIR + '/' + i for i in RGlob('src', '*.c', ['src/plasma/third_party/murmur3', 'src/modules'])]

murmur_env = c_env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])
murmur = murmur_env.Object(DEFAULT_BUILD_DIR + '/src/plasma/third_party/murmur3/murmur3.c')

csources.append(murmur)

c_lib = c_env.Library(target='dist/orion', source=csources)
c_env.Append(LIBS=c_lib)
murmur_env.Append(LIBS=c_lib)

def AddTest(target, source, env=c_env, wrap=[]):
    test_env = env.Clone()
    test_env.Append(LIBS=['cmocka'])
    for func in wrap:
        test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = test_env.Program(target=target, source=source)
    test_env.Alias('test', test, test[0].abspath)

AddTest(target='dist/tests/test_p_pool', source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_p_pool.c'])
AddTest(target='dist/tests/test_p_dlist', source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_p_dlist.c'])
AddTest(target='dist/tests/test_p_hash', env=murmur_env,
        source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_p_hash.c',
                DEFAULT_BUILD_DIR + '/src/plasma/third_party/murmur3/test.c'])
AddTest(target='dist/tests/test_p_fiber', source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_p_fiber.c'])
AddTest(target='dist/tests/test_time', source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_time.c'])
AddTest(target='dist/tests/test_p_io_provider', source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_p_io_provider.c'])
AddTest(target='dist/tests/test_trace', source=[c_lib, DEFAULT_BUILD_DIR + '/tests/test_trace.c'])
c_env.AlwaysBuild('test')

c_env.Alias('docs', c_lib, 'doxygen')
c_env.AlwaysBuild('docs')

# ----- C++ Environment ----- #

cpp_env = env.Clone()
cpp_env.Append(LIBS=c_lib)
cpp_env.Append(CXXFLAGS=['-std=c++11'])
cpp_sources = [DEFAULT_BUILD_DIR + '/' + i for i in RGlob('src', '*.cpp', [], ['src/plasma/execution/main.cpp'])]
cpp_sources = cpp_sources + [DEFAULT_BUILD_DIR + '/tests/test_module.cpp']
cpp_lib = cpp_env.Library(target='dist/orion_cpp', source=cpp_sources)
cpp_env.Append(LIBS=[cpp_lib, c_lib])
cpp_env.Program(target='dist/env', source=[DEFAULT_BUILD_DIR + '/src/plasma/execution/main.cpp'])

def AddCppTest(target, source, wrap=[]):
    cpp_test_env = cpp_env.Clone()
    cpp_test_env.Append(LIBS=['gtest'])
    for func in wrap:
        cpp_test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = cpp_test_env.Program(target=target, source=source)
    cpp_test_env.Alias('test', test, test[0].abspath)
    cpp_test_env.Alias('cpptest', test, test[0].abspath)

AddCppTest(target='dist/tests/test_assert', source=[DEFAULT_BUILD_DIR + '/tests/test_assert.cpp'])
AddCppTest(target='dist/tests/test_pool', source=[DEFAULT_BUILD_DIR + '/tests/test_pool.cpp'])
AddCppTest(target='dist/tests/test_cpool', source=[DEFAULT_BUILD_DIR + '/tests/test_cpool.cpp'], wrap=['p_silo_get_id'])
AddCppTest(target='dist/tests/test_config', source=[DEFAULT_BUILD_DIR + '/tests/test_config.cpp'])
AddCppTest(target='dist/tests/test_dlist', source=[DEFAULT_BUILD_DIR + '/tests/test_dlist.cpp'])
AddCppTest(target='dist/tests/test_io_provider', source=[DEFAULT_BUILD_DIR + '/tests/test_io_provider.cpp'])
AddCppTest(target='dist/tests/test_fiber', source=[DEFAULT_BUILD_DIR + '/tests/test_fiber.cpp'])
AddCppTest(target='dist/tests/test_env', source=[DEFAULT_BUILD_DIR + '/tests/test_env.cpp'])
AddCppTest(target='dist/tests/test_sync', source=[DEFAULT_BUILD_DIR + '/tests/test_sync.cpp'])
AddCppTest(target='dist/tests/test_hash', source=[DEFAULT_BUILD_DIR + '/tests/test_hash.cpp'])
cpp_env.AlwaysBuild('test')
cpp_env.AlwaysBuild('cpptest')

# ----- Python Environment ----- #

venv = env.Command(target='venv/requirements.txt',
                   source=['src/plasma/trace/reader/dev_requirements.txt',
                           'src/plasma/trace/reader/setup.py'],
                   action='virtualenv venv && '
                   '. venv/bin/activate && '
                   'cp $SOURCE $TARGET && '
                   'pip install -r $SOURCE && '
                   'cd src/plasma/trace/reader && '
                   'python setup.py develop')
trace_tests = env.Alias('test', [], './venv/bin/py.test src/plasma/trace/reader/tests')
Depends(trace_tests, venv)
