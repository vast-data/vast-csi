#!/usr/bin/env python
from setuptools import setup

setup(name='vproto',
      version='1.0',
      url='https://bitbucket.org/vastdev/orion',
      author='Alon Horev',
      author_email='alon@vastdata.com',
      license='Copyright (C) Vast Data Ltd.',
      packages=['vproto'],
      entry_points={'console_scripts': ['gen-vproto=vproto.main:main']},
      install_requires=['click', 'jinja2', 'ply'])
