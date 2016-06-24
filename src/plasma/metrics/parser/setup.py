#!/usr/bin/env python
from setuptools import setup

setup(name='metrics',
      version='1.0',
      url='https://bitbucket.org/vastdev/orion',
      author='Alon Horev',
      author_email='alon@vastdata.com',
      license='Copyright (C) Vast Data Ltd.',
      py_modules=['main'],
      entry_points={'console_scripts': ['gen-metrics=main:main']},
      install_requires=['click', 'jinja2', 'pyyaml'])
