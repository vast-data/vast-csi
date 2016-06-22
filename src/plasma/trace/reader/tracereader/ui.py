"""Copyright (C) Vast Data Ltd."""

import os
import re
import sys
import click
import datetime
import blessings
import collections

from .utils import merge_sort
from .parser import get_traces, get_trace_info, parse_params, printf_format_re

def c_format_to_python_format(format):
    """
    Python doesn't support %p (pointer) and %hhd (single byte integer).
    We replace %c with %d because booleans aren't supported in C's printf and are passed as %c.
    """
    return format.replace('%p', '0x%x').replace('%hhd', '%d').replace('%c', '%d')

term = blessings.Terminal()

def underline_variables(format):
    def on_match(match):
        return term.underline + match.group(0) + term.normal
    return printf_format_re.sub(on_match, format)

severities = {0: term.red + 'DEV' + term.normal,
              1: term.green + 'DBG' + term.normal,
              2: term.cyan + 'INF' + term.normal,
              3: term.yellow + 'WRN' + term.normal,
              4: term.red + 'ERR' + term.normal}

TIME_FORMAT = '%y/%m/%d %H:%M:%S.%f'
LOCATION_FORMAT = ' [{file}:{func}:{line}]'
TRACE_FORMAT = '{time} ({tid:5d}|{job_id:08x}) [{component:.4}] {severity}{location}: {message}'
file_re = re.compile(r'(\w+)\.(\d+)')
def print_trace(trace, verbose):
    time = datetime.datetime.fromtimestamp(trace.header.time / 1000000000.).strftime(TIME_FORMAT)
    message = c_format_to_python_format(underline_variables(trace.info.format)) % tuple(trace.params)
    location = LOCATION_FORMAT.format(file=trace.info.file.rsplit('/', 1)[1],
                                      func=term.bold + trace.info.func + term.normal,
                                      line=trace.info.line) if verbose else ''
    print(TRACE_FORMAT.format(time=time,
                              message=message,
                              location=location,
                              component=trace.component,
                              tid=int(trace.tid),
                              job_id=trace.header.job_id,
                              severity=severities[trace.header.severity]))

def print_error(msg):
    print(term.red + 'READER ERROR: ' + msg + term.normal)

Trace = collections.namedtuple('Trace', ['info', 'header', 'params', 'component', 'tid'])
def handle_path(path):
    assert os.path.exists(path), 'File does not exist: {}'.format(path)
    match = file_re.search(path)
    assert match is not None, 'Not a trace file: {}'.format(path)
    assert os.stat(path).st_size > 0, 'Trace file is empty: {}'.format(path)
    component, tid = match.groups()
    with open(path, 'rb') as f:
        for info, header, params in get_traces(f, get_trace_info(f)):
            yield Trace(info=info, header=header, params=params, component=component, tid=tid)

def safe_handle_path(path):
    try:
        yield from handle_path(path)
    except Exception as e:
        # an assertion is fatal. otherwise, hide the error for other files to continue parsing
        if isinstance(e, AssertionError):
            print_error(str(e))
            sys.exit(1)
        print_error('Failed parsing trace file:' + path)

def run(paths, verbose):
    for trace in merge_sort(map(safe_handle_path, paths), lambda trace: trace.header.time):
        print_trace(trace, verbose)

@click.command()
@click.argument('paths', nargs=-1)
@click.option('-v', '--verbose', is_flag=True)
def main(paths, verbose):
    run(paths, verbose)

if __name__ == '__main__':
    main()
