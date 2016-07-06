"""Copyright (C) Vast Data Ltd."""

import os
import re
import yaml
import click
from jinja2 import Environment, PackageLoader, StrictUndefined


env = Environment(loader=PackageLoader(__name__, 'templates'),
                  undefined=StrictUndefined,
                  lstrip_blocks=True,
                  trim_blocks=True)


def camel_case_to_snake_case(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class Method(object):
    def __init__(self, method_dict):
        self.name = method_dict['method']
        self.arg = method_dict['arg']
        self.arg_snake_case = camel_case_to_snake_case(self.arg)
        self.res = method_dict['res']
        self.res_snake_case = camel_case_to_snake_case(self.res)
        self.op_id = method_dict['op_id']
        self.fiber_group = method_dict['fiber_group']


class Module(object):
    def __init__(self, module_dict):
        self.name = module_dict['class']
        self.include = module_dict.get('include', None)
        self.module_id = module_dict['module_id']
        self.api_version = module_dict['api_version']
        self.namespaces = module_dict.get('namespaces', [])
        self.methods = [Method(method) for method in module_dict['methods']]
        self.name_snake_case = camel_case_to_snake_case(self.name)

    def generate_file(self, template_file, output_file):
        print("generating {}".format(output_file))
        template = env.get_template(template_file)
        if os.path.exists(output_file):
            os.chmod(output_file, 0o755)
        with open(output_file, 'w') as f:
            for line in template.generate(module=self):
                f.write(line)

    def generate(self, output_file_prefix):
        args = [('server_header.jin', output_file_prefix + '.server.hpp'),
                ('server_impl.jin', output_file_prefix + '.server.cpp'),
                ('client_header.jin', output_file_prefix + '.client.hpp'),
                ('client_impl.jin', output_file_prefix + '.client.cpp')]
        for template, output in args:
            self.generate_file(template, output)


def rpc_gen(input_file, output_file_prefix):
    module_dict = yaml.load(open(input_file))
    module = Module(module_dict)
    module.generate(output_file_prefix)


@click.command()
@click.argument('input-file')
@click.argument('output-file-prefix')
@click.option('-d', '--debug', is_flag=True)
def main(input_file, output_file_prefix, debug):
    try:
        rpc_gen(input_file, output_file_prefix)
    except:
        if debug:
            import pdb
            pdb.post_mortem()
        raise


if __name__ == '__main__':
    main()
