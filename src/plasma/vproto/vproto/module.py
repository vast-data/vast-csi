import os
import datetime
from .parser import parse, Struct, Enum, Directive
from .struct import VProtoStruct, VProtoEnum, TypeRegistry, SchemaError
from jinja2 import Environment, PackageLoader, StrictUndefined

env = Environment(loader=PackageLoader(__name__, 'templates'),
                  undefined=StrictUndefined,
                  lstrip_blocks=True,
                  trim_blocks=True)

DIRECTIVES = {}
def register_directive(name):
    def decorator(func):
        DIRECTIVES[name] = func
        return func
    return decorator

@register_directive('namespace')
def namespace_directive(options, value):
    if options['namespaces'] != []:
        raise SchemaError("The 'namespace' directive can only be used once.")
    options['namespaces'] = value.split('::')

@register_directive('import')
def import_directive(options, value):
    label = None
    try:
        path, _, label = value.split()
    except ValueError:
        path = value
    options['imports'][path] = label

@register_directive('typedef')
def typedef_directive(options, value):
    type_name, alias = value.strip(';').split(' ')
    if type_name in options['typedefs']:
        raise SchemaError("The '{}' type is already defined".format(type_name))
    options['typedefs'][alias] = type_name

@register_directive('const')
def const_directive(options, value):
    # example value: int COUNT = 3;
    type, pair = value.split(' ', 1)
    name, value = map(str.strip, pair.split('='))
    if name in options['consts']:
        raise SchemaError("The '{}' const is already defined".format(name))
    options['consts'][name] = (type, value)

def parse_directives(directives):
    options = {'namespaces': [], 'imports': {}, 'typedefs': {}, 'consts': {}}
    for directive in directives:
        command, value = directive.value.split(' ', 1)
        try:
            func = DIRECTIVES[command]
        except KeyError:
            raise SchemaError('Unsupported directive: {}. Options: {}'.format(command, ', '.join(DIRECTIVES.keys())))
        else:
            func(options, value)
    return options

def find_module(path, import_path=None):
    if import_path is None:
        import_path = ''
    import_path = '.:' + import_path

    for prefix in import_path.split(':'):
        full_path = os.path.join(prefix, path)
        if os.path.exists(full_path):
            return full_path
    raise SchemaError('Cannot find module: {}. Validate the path is correct or perhaps an --import-path is missing.'.format(path))

class VProtoModule(object):
    def __init__(self, path, registry, import_path=None):
        self.path = find_module(path, import_path)
        with open(self.path) as proto_file:
            defs = parse(proto_file.read())

        directives = []
        for i in defs:
            if isinstance(i, Directive):
                directives.append(i)
        self.options = parse_directives(directives)
        for path, label in self.options['imports'].items():
            module_registry = TypeRegistry()
            try:
                VProtoModule(path, module_registry, import_path + ':' + os.path.dirname(self.path))
            except Exception as e:
                raise SchemaError('Failed parsing imported module: {} with error: {}'.format(path, str(e))) from e
            registry.merge(module_registry, label)

        for alias, type_name in self.options['typedefs'].items():
            registry.add_alias(type_name, alias)

        for name, (type, value) in self.options['consts'].items():
            registry.add_const(name, type, value)

        self.structs = []
        self.enums = []
        for i in defs:
            if isinstance(i, Struct):
                self.structs.append(VProtoStruct(i, self, registry))
            elif isinstance(i, Enum):
                self.enums.append(VProtoEnum(i, self, registry))

    def get_namespace(self):
        return '::'.join(self.options['namespaces'])

    def get_fqn(self, field):
        if field.type.module == self:
            return field.type.name

        ns = field.type.module.get_namespace()
        if ns:
            return ns + '::' + field.type.name
        return field.type.name

    def render(self, path):
        with open(path, 'w') as f:
            f.write(env.get_template('header.jin').render(source_path=self.path,
                                                          generation_time=datetime.datetime.now(),
                                                          structs=self.structs,
                                                          enums=self.enums,
                                                          get_fqn=self.get_fqn,
                                                          **self.options))
