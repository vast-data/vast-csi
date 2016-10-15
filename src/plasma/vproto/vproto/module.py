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
    def decorator(cls):
        DIRECTIVES[name] = cls
        return cls
    return decorator

@register_directive('namespace')
class NamespaceDirective(object):
    def __init__(self, value):
        self.namespaces = value.split('::')

@register_directive('import')
class ImportDirective(object):
    def __init__(self, value):
        self.label = None
        try:
            self.path, _, self.label = value.split()
        except ValueError:
            self.path = value

@register_directive('typedef')
class TypedefDirective(object):
    def __init__(self, value):
        self.type, self.alias = value.split(' ')

@register_directive('const')
class ConstDirective(object):
    def __init__(self, value):
        # example value: int COUNT = 3;
        self.type, pair = value.split(' ', 1)
        self.name, self.value = map(str.strip, pair.split('='))

def parse_directive(directive):
    name, value = directive.value.split(' ', 1)
    try:
        func = DIRECTIVES[name]
    except KeyError:
        raise SchemaError('Unsupported directive: {}. Options: {}'.format(name, ', '.join(DIRECTIVES.keys())))
    return func(value)

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

        self.defs = []
        self.namespaces = []
        self.imports = []
        self.names = []

        for i in defs:
            if isinstance(i, Directive):
                directive = parse_directive(i)
                if isinstance(directive, NamespaceDirective):
                    if self.namespaces:
                        raise SchemaError("The 'namespace' directive can only be used once.")
                    self.namespaces = directive.namespaces
                    continue
                elif isinstance(directive, ImportDirective):
                    module_registry = TypeRegistry()
                    try:
                        VProtoModule(directive.path, module_registry,
                                     import_path + ':' + os.path.dirname(self.path))
                    except Exception as e:
                        raise SchemaError('Failed parsing imported module: {} with error: {}'.format(directive.path, str(e))) from e
                    registry.merge(module_registry, directive.label)
                    self.imports.append(directive.path)
                    continue
                elif isinstance(directive, TypedefDirective):
                    registry.add_alias(directive.type, directive.alias)
                elif isinstance(directive, ConstDirective):
                    registry.add_const(directive.name, directive.type, directive.value)
                self.defs.append(directive)
            elif isinstance(i, Struct):
                self.defs.append(VProtoStruct(i, self, registry))
            elif isinstance(i, Enum):
                self.defs.append(VProtoEnum(i, self, registry))
            else:
                assert False

    def get_namespace(self):
        return '::'.join(self.namespaces)

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
                                                          defs=self.defs,
                                                          imports=self.imports,
                                                          namespaces=self.namespaces,
                                                          typename=lambda x: x.__class__.__name__,
                                                          get_fqn=self.get_fqn))
