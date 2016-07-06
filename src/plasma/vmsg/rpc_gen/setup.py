#!/usr/bin/env python
from setuptools import setup

setup(name='rpc',
      version='1.0',
      url='https://bitbucket.org/vastdev/orion',
      author='Asaf Levy',
      author_email='asaf@vastdata.com',
      license='Copyright (C) Vast Data Ltd.',
      py_modules=['rpc_gen'],
      entry_points={'console_scripts': ['gen-rpc=rpc_gen:main']},
      install_requires=['click', 'jinja2', 'pyyaml'])
