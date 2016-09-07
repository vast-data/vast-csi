from .module import VProtoModule, TypeRegistry
import click

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
