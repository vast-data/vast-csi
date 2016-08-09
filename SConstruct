import fnmatch
import re
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
4. test_* - build and invoke C++ test executable.
5. pytest - run python tests.
6. nfstest - run nfs tests.
7. docs - builds the documentation. The result is located at docs/html/index.html.

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
    build_dir = DEFAULT_BUILD_DIR + '/debug'
    optimizations = '0'
    env.Append(CPPDEFINES=['DEBUG'])
else:
    build_dir = DEFAULT_BUILD_DIR + '/release'

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
env.Append(CPPPATH=[build_dir + '/src'])
env.Append(LINKFLAGS=['-pthread'])

murmur_env = env.Clone()
murmur_env.Append(CFLAGS=['-Wno-cast-align',
                          '-Wno-sign-conversion',
                          '-Wno-shorten-64-to-32',
                          '-Wno-incompatible-pointer-types-discards-qualifiers'])

c_env = env.Clone()
c_env.Append(CFLAGS=['-Wno-cast-align',
                     '-Wno-sign-conversion',
                     '-Wno-shorten-64-to-32',
                     '-Wno-incompatible-pointer-types-discards-qualifiers',
                     '-Wno-unused-variable',
                     '-Wno-switch-enum',
                     '-Wno-zero-length-array',
                     '-Wno-covered-switch-default',
                     '-Wno-typedef-redefinition'])
murmur = c_env.Object(build_dir + '/src/plasma/third_party/murmur3/murmur3.c')
rpc_xdr = c_env.Object(build_dir + '/src/proto/nfs3/rpcgen/rpc_defs_xdr.c')
mnt_xdr = c_env.Object(build_dir + '/src/proto/nfs3/rpcgen/mnt3_xdr.c')
nfs_xdr = c_env.Object(build_dir + '/src/proto/nfs3/rpcgen/nfs3_xdr.c')

VariantDir(build_dir + '/src', 'src')
VariantDir(build_dir + '/tests', 'tests')

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
    rpc_file = build_dir + '/' + rpc_file
    rpc_sources.extend(FilterPaths(env.Rpc(rpc_file), '*.cpp'))
test_rpc_sources = FilterPaths(env.Rpc(build_dir + '/tests/test_rpc.rpc'), '*.cpp')

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
    metric_file = build_dir + '/' + metric_file
    metric_sources.extend(FilterPaths(env.Metrics(metric_file), '*.cpp'))
test_metric_sources = FilterPaths(env.Metrics(build_dir + '/tests/test.metrics'), '*.cpp')

# ----- VProto ----- #
VPROTO_INCLUDE_DIRS = ['src', 'tests']
import_re = re.compile(r'^\$import (\S+)(?: as \S+)?$', re.M)
def vproto_scan(node, env, path):
    contents = node.get_contents()
    imports = []
    for i in import_re.findall(contents):
        for d in VPROTO_INCLUDE_DIRS:
            full_path = os.path.join(d, i)
            if os.path.exists(full_path):
                # the '#' prefix makes scons look for the file from the root of the project (vs. relatively to the file).
                imports.append('#' + full_path)
    return imports

def vproto_emitter(target, source, env):
    source.extend([vproto_gen,
                   'src/plasma/vproto/vproto/main.py',
                   'src/plasma/vproto/vproto/struct.py',
                   'src/plasma/vproto/vproto/parser.py',
                   'src/plasma/vproto/vproto/templates/header.jin'])
    return str(source[0]) + '.hpp', source
env.Append(BUILDERS = {'VProto': Builder(action='./venv/bin/gen-vproto -i {} $SOURCE $SOURCE'.format(':'.join(VPROTO_INCLUDE_DIRS)), emitter=vproto_emitter)},
           SCANNERS = Scanner(function=vproto_scan, skeys=['.vproto']))

for metric_file in RGlob('src', '*.vproto') + RGlob('tests', '*.vproto'):
    metric_file = build_dir + '/' + metric_file
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
cpp_sources = [build_dir + '/' + i for i in RGlob('src', '*.cpp', [], ['src/plasma/execution/main.cpp'])]
cpp_sources.extend(rpc_sources)
cpp_sources.append(build_dir + '/tests/test_module.cpp')
cpp_sources.extend([murmur, rpc_xdr, mnt_xdr, nfs_xdr])
cpp_lib = cpp_env.Library(target='dist/orion_cpp', source=cpp_sources)
cpp_env.Depends(cpp_lib, LINKER_SCRIPT)
cpp_env.Append(LIBS=[cpp_lib, 'unwind', 'config', 'libaio', 'rdmacm', 'ibverbs'])
cpp_env.Program(target='dist/env', source=[build_dir + '/src/plasma/execution/main.cpp'])

def AddCppTest(target, source, wrap=[], group_alias='cpptest'):
    cpp_test_env = cpp_env.Clone()
    cpp_test_env.Append(LIBS=['gtest', 'rt'])
    cpp_test_env.Append(CPPPATH=[build_dir + '/tests'])
    for func in wrap:
        cpp_test_env.Append(LINKFLAGS='-Wl,-wrap,' + func)
    test = cpp_test_env.Program(target=target, source=source)
    for alias in [group_alias, 'test_' + target.split('/')[-1]]:
        cpp_test_env.Alias(alias, test, test[0].abspath)
        cpp_test_env.AlwaysBuild(alias)

env.Alias('cpptest', env.Command('<phony1>', [], 'sudo modprobe siw'))
env.Alias('cpptest', env.Command('<phony2>', [], 'sudo rpcbind ; true'))
env.Alias('nfstest', env.Command('<phony3>', [], 'sudo rpcbind ; true'))

AddCppTest(target='dist/tests/assert', source=[build_dir + '/tests/test_assert.cpp'])
AddCppTest(target='dist/tests/pool', source=[build_dir + '/tests/test_pool.cpp'])
AddCppTest(target='dist/tests/object_pool', source=[build_dir + '/tests/test_object_pool.cpp'])
AddCppTest(target='dist/tests/atomic_pool', source=[build_dir + '/tests/test_atomic_pool.cpp'])
AddCppTest(target='dist/tests/cpool', source=[build_dir + '/tests/test_cpool.cpp'], wrap=['p_silo_get_id'])
AddCppTest(target='dist/tests/config', source=[build_dir + '/tests/test_config.cpp'])
AddCppTest(target='dist/tests/dlist', source=[build_dir + '/tests/test_dlist.cpp'])
AddCppTest(target='dist/tests/list', source=[build_dir + '/tests/test_list.cpp'])
AddCppTest(target='dist/tests/io_provider', source=[build_dir + '/tests/test_io_provider.cpp'])
AddCppTest(target='dist/tests/fiber', source=[build_dir + '/tests/test_fiber.cpp'])
AddCppTest(target='dist/tests/env', source=[build_dir + '/tests/test_env.cpp'])
AddCppTest(target='dist/tests/sync', source=[build_dir + '/tests/test_sync.cpp'])
AddCppTest(target='dist/tests/fiber_sync', source=[build_dir + '/tests/test_fiber_sync.cpp'])
AddCppTest(target='dist/tests/hash', source=[build_dir + '/tests/test_hash.cpp'])
AddCppTest(target='dist/tests/queue', source=[build_dir + '/tests/test_queue.cpp'])
AddCppTest(target='dist/tests/trace', source=[build_dir + '/tests/test_trace.cpp'])
AddCppTest(target='dist/tests/spsc_queue', source=[build_dir + '/tests/test_spsc_queue.cpp'])
AddCppTest(target='dist/tests/time', source=[build_dir + '/tests/test_time.cpp'])
AddCppTest(target='dist/tests/perf', source=[build_dir + '/tests/test_perf.cpp'])
AddCppTest(target='dist/tests/metrics', source=[build_dir + '/tests/test_metrics.cpp', test_metric_sources])
AddCppTest(target='dist/tests/rdma_transport', source=[build_dir + '/tests/test_rdma_transport.cpp'])
AddCppTest(target='dist/tests/vmsg', source=[build_dir + '/tests/vmsg_test.cpp', test_rpc_sources])
AddCppTest(target='dist/tests/vproto', source=[build_dir + '/tests/test_vproto.cpp'])
AddCppTest(target='dist/tests/nfs_rpc', source=[build_dir + '/tests/test_nfs_rpc.cpp'])
AddCppTest(target='dist/tests/nfs', source=[build_dir + '/tests/test_nfs.cpp'], group_alias='nfstest')

cpp_env.AlwaysBuild('nfstest')
cpp_env.AlwaysBuild('cpptest')
env.Alias('test', 'cpptest')
