#!/usr/bin/env python

from setuptools import setup

setup(name='tracereader',
      version='1.0',
      url='https://bitbucket.org/vastdev/orion',
      author='Alon Horev',
      author_email='alon@vastdata.com',
      packages=['tracereader'],
      entry_points={'console_scripts': ['hubble=tracereader.ui:main']},
      install_requires=['blessings'])
