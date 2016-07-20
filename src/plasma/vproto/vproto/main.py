import os
import click
from .parser import parse, Struct, Enum, Directive
from .struct import VProtoStruct, TypeRegistry, SchemaError
from jinja2 import Environment, PackageLoader, StrictUndefined

env = Environment(loader=PackageLoader(__name__, 'templates'),
                  undefined=StrictUndefined,
                  lstrip_blocks=True,
                  trim_blocks=True)

def parse_directives(directives):
    options = {'namespaces': []}
    for directive in directives:
        command, value = directive.value.split(' ', 1)
        if command != 'namespace':
            raise SchemaError('Unsupported directive: {}. Options: namespace'.format(command))
        options['namespaces'] = value.split('::')
    return options

def convert(proto_file, output_prefix):
    with open(proto_file) as proto:
        defs = parse(proto.read())
    registry = TypeRegistry()
    structs = []
    enums = []
    directives = []
    for i in defs:
        if isinstance(i, Struct):
            structs.append(VProtoStruct(i, registry))
        elif isinstance(i, Enum):
            registry.add_enum(i)
            enums.append(i)
        if isinstance(i, Directive):
            directives.append(i)
    cpp_options = parse_directives(directives)
    with open(output_prefix + '.hpp', 'w') as f:
        f.write(env.get_template('header.jin').render(structs=structs, enums=enums, **cpp_options))

@click.command()
@click.argument('proto-file')
@click.argument('output-prefix')
@click.option('-d', '--debug', is_flag=True)
def main(proto_file, output_prefix, debug):
    try:
        convert(proto_file, output_prefix)
    except Exception as e:
        if debug:
            import pdb
            pdb.post_mortem()
        raise

if __name__ == '__main__':
    main()
