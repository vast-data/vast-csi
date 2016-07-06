import os
import yaml
import click
from jinja2 import Environment, PackageLoader, StrictUndefined

print(__name__)
env = Environment(loader=PackageLoader(__name__, 'templates'),
                  undefined=StrictUndefined,
                  lstrip_blocks=True,
                  trim_blocks=True)

def convert(metrics, output_prefix):
    with open(metrics) as metrics_file:
        defs = yaml.load(metrics_file.read())
    header = os.path.split(output_prefix)[-1] + '.hpp'
    for suffix, template in [('.hpp', 'header.jin'),
                             ('.cpp', 'source.jin')]:
        with open(output_prefix + suffix, 'w') as f:
            f.write(env.get_template(template).render(defs=defs, header=header))

@click.command()
@click.argument('metrics')
@click.argument('output-prefix')
@click.option('-d', '--debug', is_flag=True)
def main(metrics, output_prefix, debug):
    try:
        convert(metrics, output_prefix)
    except Exception as e:
        if debug:
            import pdb
            pdb.post_mortem()
        raise

if __name__ == '__main__':
    main()
