import os
import click
import datetime
from .parser import parse, Struct, Enum, Directive
from .struct import VProtoStruct, TypeRegistry, SchemaError
from jinja2 import Environment, PackageLoader, StrictUndefined

env = Environment(loader=PackageLoader(__name__, 'templates'),
                  undefined=StrictUndefined,
                  lstrip_blocks=True,
                  trim_blocks=True)

def parse_directives(directives):
    options = {'namespaces': [], 'imports': {}, 'typedefs': {}}
    for directive in directives:
        command, value = directive.value.split(' ', 1)
        if command == 'namespace':
            if options['namespaces'] != []:
                raise SchemaError("The 'namespace' directive can only be used once.")
            options['namespaces'] = value.split('::')
        elif command == 'import':
            label = None
            try:
                path, _, label = value.split()
            except ValueError:
                path = value
            options['imports'][path] = label
        elif command == 'typedef':
            type_name, alias = value.split(' ')
            if type_name in options['typedefs']:
                raise SchemaError("The '{}' type is already defined".format(type_name))
            options['typedefs'][alias] = type_name
        else:
            raise SchemaError('Unsupported directive: {}. Options: namespace, import'.format(command))
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
            VProtoModule(path, module_registry, import_path)
            registry.merge(module_registry, label)

        for alias, type_name in self.options['typedefs'].items():
            registry.add_alias(type_name, alias)

        self.structs = []
        self.enums = []
        for i in defs:
            if isinstance(i, Struct):
                self.structs.append(VProtoStruct(i, self, registry))
            elif isinstance(i, Enum):
                registry.add_enum(self, i)
                self.enums.append(i)

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

def convert(proto_file, output_prefix, import_path=None):
    registry = TypeRegistry()
    module = VProtoModule(proto_file, registry, import_path)
    module.render(output_prefix + '.hpp')

@click.command()
@click.argument('proto-file')
@click.argument('output-prefix')
@click.option('-i', '--import-path')
@click.option('-d', '--debug', is_flag=True)
def main(proto_file, output_prefix, import_path, debug):
    try:
        convert(proto_file, output_prefix, import_path)
    except Exception as e:
        if debug:
            import pdb
            pdb.post_mortem()
        raise

if __name__ == '__main__':
    main()
