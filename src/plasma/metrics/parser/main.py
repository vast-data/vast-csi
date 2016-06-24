import yaml
import click
from jinja2 import Environment, PackageLoader, StrictUndefined

def convert(metrics, header):
    env = Environment(loader=PackageLoader(__name__, 'templates'),
                      undefined=StrictUndefined,
                      lstrip_blocks=True,
                      trim_blocks=True)

    with open(metrics) as metrics_file:
        defs = yaml.load(metrics_file.read())
    with open(header, 'w') as header_file:
        header_file.write(env.get_template('header.jin').render(defs=defs))

@click.command()
@click.argument('metrics')
@click.argument('header')
@click.option('-d', '--debug', is_flag=True)
def main(metrics, header, debug):
    try:
        convert(metrics, header)
    except Exception as e:
        if debug:
            import pdb
            pdb.post_mortem()
        raise

if __name__ == '__main__':
    main()
