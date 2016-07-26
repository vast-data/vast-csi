import fnmatch
import os

DEFAULT_COMPILER = 'clang'
DEFAULT_OPTIMIZATION_LEVEL = '2'
DEFAULT_BUILD_DIR = 'build'

def FilterPaths(paths, pattern):
   return fnmatch.filter(map(str, paths), pattern)

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
2. test - builds and invoke all tests.
3. cpptest - builds and invoke C++ tests.
4. pytest - run python tests.
5. docs - builds the documentation. The result is located at docs/html/index.html.

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
env.Append(CPPPATH=['build/src'])
env.Append(LINKFLAGS=['-pthread'])

murmur_env = env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])
murmur = murmur_env.Object(DEFAULT_BUILD_DIR + '/src/plasma/third_party/murmur3/murmur3.c')

# ----- Python Environment ----- #
venv = env.Command(target='venv/requirements.txt',
                   source=['python_requirements.txt'],
                   action='virtualenv venv && '
                   '. venv/bin/activate && '
                   'cp $SOURCE $TARGET && '
                   'pip install -r $SOURCE')

def develop_package(target, dir):
    package = env.Command(target, [dir + '/setup.py'], action='. venv/bin/activate && pushd `dirname $SOURCE` && python3 setup.py develop && popd && cp ' + dir + '/setup.py $TARGET')
    env.Depends(package, venv)
    env.SideEffect('venv/lib/python3.4/site-packages/easy-install.pth', package)
    return package

rpc_gen = develop_package('venv/rpc_installed.txt', 'src/plasma/vmsg/rpc_gen')
metrics_gen = develop_package('venv/metrics_installed.txt', 'src/plasma/metrics/parser')
vproto_gen = develop_package('venv/vproto_installed.txt', 'src/plasma/vproto')
vproto_tests = env.Alias('pytest', [], './venv/bin/py.test src/plasma/vproto/test.py')
env.Depends(vproto_tests, vproto_gen)
hubble = develop_package('venv/trace_installed.txt', 'src/plasma/trace/reader')
trace_tests = env.Alias('pytest', [], './venv/bin/py.test src/plasma/trace/reader/tests')
env.Depends(trace_tests, hubble)

env.AlwaysBuild('pytest')
env.Alias('test', 'pytest')

# ----- RPC ----- #
def rpc_emitter(target, source, env):
    assert len(source) == 1
    # regenerate template if the package dependencies change or any of its file
    source.extend([rpc_gen,
                   'src/plasma/vmsg/rpc_gen/rpc_gen.py',
                   'src/plasma/vmsg/rpc_gen/templates/client_header.jin',
                   'src/plasma/vmsg/rpc_gen/templates/client_impl.jin',
                   'src/plasma/vmsg/rpc_gen/templates/server_header.jin',
                   'src/plasma/vmsg/rpc_gen/templates/server_impl.jin'])
    targets = [str(source[0]) + suffix for suffix in ('.server.cpp', '.server.hpp', '.client.cpp', '.client.hpp')]
    return targets, source
env.Append(BUILDERS = {'Rpc': Builder(action='./venv/bin/gen-rpc $SOURCE $SOURCE', emitter=rpc_emitter)})

rpc_sources = []
for rpc_file in RGlob('src', '*.rpc'):
    rpc_file = DEFAULT_BUILD_DIR + '/' + rpc_file
    rpc_sources.extend(FilterPaths(env.Rpc(rpc_file), '*.cpp'))
test_rpc_sources = FilterPaths(env.Rpc(DEFAULT_BUILD_DIR + '/tests/test_rpc.rpc'), '*.cpp')

# ----- Metrics ----- #
def metrics_emitter(target, source, env):
    source.extend([metrics_gen,
                   'src/plasma/metrics/parser/metrics_gen.py',
                   'src/plasma/metrics/parser/templates/header.jin',
                   'src/plasma/metrics/parser/templates/source.jin'])
    targets = [str(source[0]) + suffix for suffix in ('.hpp', '.cpp')]
    return targets, source
env.Append(BUILDERS = {'Metrics': Builder(action='./venv/bin/gen-metrics $SOURCE $SOURCE', emitter=metrics_emitter)})

metric_sources = []
for metric_file in RGlob('src', '*.metrics'):
    metric_file = DEFAULT_BUILD_DIR + '/' + metric_file
    metric_sources.extend(FilterPaths(env.Metrics(metric_file), '*.cpp'))
test_metric_sources = FilterPaths(env.Metrics(DEFAULT_BUILD_DIR + '/tests/test.metrics'), '*.cpp')

# ----- VProto ----- #
def vproto_emitter(target, source, env):
    source.extend([vproto_gen,
                   'src/plasma/vproto/vproto/main.py',
                   'src/plasma/vproto/vproto/struct.py',
                   'src/plasma/vproto/vproto/parser.py',
                   'src/plasma/vproto/vproto/templates/header.jin'])
    return str(source[0]) + '.hpp', source
env.Append(BUILDERS = {'VProto': Builder(action='./venv/bin/gen-vproto -i build/src:build/tests $SOURCE $SOURCE', emitter=vproto_emitter)})

for metric_file in RGlob('src', '*.vproto') + RGlob('tests', '*.vproto'):
    metric_file = DEFAULT_BUILD_DIR + '/' + metric_file
    env.VProto(metric_file)

# ----- C++ Environment ----- #
LINKER_SCRIPT = 'linkerscript.lds'

cpp_env = env.Clone()
cpp_env.Append(CXXFLAGS=['-std=c++11',
                         '-Wno-invalid-offsetof']) # offsetof should work on non-POD objects as well
if compiler == 'gcc':
   cpp_env.Append(LINKFLAGS=['-T' + LINKER_SCRIPT])
pre = ARGUMENTS.get('pre')
if pre is not None:
   cpp_env.Append(CCFLAGS=['-E'])
cpp_sources = [DEFAULT_BUILD_DIR + '/' + i for i in RGlob('src', '*.cpp', [], ['src/plasma/execution/main.cpp'])]
cpp_sources.extend(rpc_sources)
cpp_sources.append(DEFAULT_BUILD_DIR + '/tests/test_module.cpp')
cpp_sources.append(murmur)
cpp_lib = cpp_env.Library(target='dist/orion_cpp', source=cpp_sources)
cpp_env.Depends(cpp_lib, LINKER_SCRIPT)
cpp_env.Append(LIBS=[cpp_lib, 'unwind', 'config', 'libaio', 'rdmacm', 'ibverbs'])
cpp_env.Program(target='dist/env', source=[DEFAULT_BUILD_DIR + '/src/plasma/execution/main.cpp'])

def AddCppTest(target, source, wrap=[]):
    cpp_test_env = cpp_env.Clone()
    cpp_test_env.Append(LIBS=['gtest', 'rt'])
    cpp_test_env.Append(CPPPATH=['build/tests'])
    for func in wrap:
        cpp_test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = cpp_test_env.Program(target=target, source=source)
    cpp_test_env.Alias('cpptest', test, test[0].abspath)
env.Alias('cpptest', env.Command('<phony>', [], 'sudo modprobe siw'))

AddCppTest(target='dist/tests/assert', source=[DEFAULT_BUILD_DIR + '/tests/test_assert.cpp'])
AddCppTest(target='dist/tests/pool', source=[DEFAULT_BUILD_DIR + '/tests/test_pool.cpp'])
AddCppTest(target='dist/tests/object_pool', source=[DEFAULT_BUILD_DIR + '/tests/test_object_pool.cpp'])
AddCppTest(target='dist/tests/atomic_pool', source=[DEFAULT_BUILD_DIR + '/tests/test_atomic_pool.cpp'])
AddCppTest(target='dist/tests/cpool', source=[DEFAULT_BUILD_DIR + '/tests/test_cpool.cpp'], wrap=['p_silo_get_id'])
AddCppTest(target='dist/tests/config', source=[DEFAULT_BUILD_DIR + '/tests/test_config.cpp'])
AddCppTest(target='dist/tests/dlist', source=[DEFAULT_BUILD_DIR + '/tests/test_dlist.cpp'])
AddCppTest(target='dist/tests/list', source=[DEFAULT_BUILD_DIR + '/tests/test_list.cpp'])
AddCppTest(target='dist/tests/io_provider', source=[DEFAULT_BUILD_DIR + '/tests/test_io_provider.cpp'])
AddCppTest(target='dist/tests/fiber', source=[DEFAULT_BUILD_DIR + '/tests/test_fiber.cpp'])
AddCppTest(target='dist/tests/env', source=[DEFAULT_BUILD_DIR + '/tests/test_env.cpp'])
AddCppTest(target='dist/tests/sync', source=[DEFAULT_BUILD_DIR + '/tests/test_sync.cpp'])
AddCppTest(target='dist/tests/fiber_sync', source=[DEFAULT_BUILD_DIR + '/tests/test_fiber_sync.cpp'])
AddCppTest(target='dist/tests/hash', source=[DEFAULT_BUILD_DIR + '/tests/test_hash.cpp'])
AddCppTest(target='dist/tests/queue', source=[DEFAULT_BUILD_DIR + '/tests/test_queue.cpp'])
AddCppTest(target='dist/tests/trace', source=[DEFAULT_BUILD_DIR + '/tests/test_trace.cpp'])
AddCppTest(target='dist/tests/spsc_queue', source=[DEFAULT_BUILD_DIR + '/tests/test_spsc_queue.cpp'])
AddCppTest(target='dist/tests/time', source=[DEFAULT_BUILD_DIR + '/tests/test_time.cpp'])
AddCppTest(target='dist/tests/perf', source=[DEFAULT_BUILD_DIR + '/tests/test_perf.cpp'])
AddCppTest(target='dist/tests/metrics', source=[DEFAULT_BUILD_DIR + '/tests/test_metrics.cpp', test_metric_sources])
AddCppTest(target='dist/tests/rdma_transport', source=[DEFAULT_BUILD_DIR + '/tests/test_rdma_transport.cpp'])
AddCppTest(target='dist/tests/vmsg', source=[DEFAULT_BUILD_DIR + '/tests/vmsg_test.cpp', test_rpc_sources])
AddCppTest(target='dist/tests/vproto', source=[DEFAULT_BUILD_DIR + '/tests/test_vproto.cpp'])

cpp_env.AlwaysBuild('cpptest')
env.Alias('test', 'cpptest')
