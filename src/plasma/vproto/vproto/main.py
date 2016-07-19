import os
import click
from .parser import parse, Struct, Enum, Directive
from jinja2 import Environment, PackageLoader, StrictUndefined

class SchemaError(Exception): pass

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

def validate_struct(struct):
    indices = []
    for field in struct.fields:
        if field.type.elements is not None and field.default is not None:
            raise SchemaError('Array fields cannot have default values: {}.{}'.format(struct.name.value, field.name.value))
        indices.append(field.index.value)

    indices.sort()
    missing = set(range(indices[-1])) - set(indices)
    if missing:
        raise SchemaError('Struct {} is missing indices: {}'.format(struct.name.value, ', '.join(map(str, missing))))

def convert(proto_file, output_prefix):
    with open(proto_file) as proto:
        defs = parse(proto.read())
    structs = []
    enums = []
    directives = []
    for i in defs:
        if isinstance(i, Struct):
            validate_struct(i)
            structs.append(i)
        elif isinstance(i, Enum):
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
