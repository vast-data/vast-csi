"""Copyright (C) Vast Data Ltd."""

import os
import re
import sys
import click
import datetime
import blessings
import traceback
import collections

from .utils import merge_sort
from .parser import get_traces, get_trace_info, parse_params, printf_format_re

def c_format_to_python_format(format):
    """
    Python doesn't support %p (pointer) and %hhd (single byte integer).
    We replace %c with %d because booleans aren't supported in C's printf and are passed as %c.
    """
    return format.replace('%p', '0x%x').replace('%hh', '%').replace('%c', '%d').replace('%z', '%d')

term = blessings.Terminal(force_styling=True)

def underline_variables(format):
    def on_match(match):
        return term.underline + match.group(0) + term.normal
    return printf_format_re.sub(on_match, format)

severities = {0: term.red + 'DEV' + term.normal,
              1: term.green + 'DBG' + term.normal,
              2: term.cyan + 'INF' + term.normal,
              3: term.yellow + 'WRN' + term.normal,
              4: term.red + 'ERR' + term.normal}
components = {0: 'TEST',
              1: 'PLAS',
              2: 'NFS ',
              3: 'CLUS',
             }

TIME_FORMAT = '%y/%m/%d %H:%M:%S.%f'
LOCATION_FORMAT = ' [{channel}:{file}:{func}:{line}]'
TRACE_FORMAT = '{time} ({pid:5d}|{tid:5d}|{job_id:08x}) [{component:.4}] {severity}{location}: {message}'
file_re = re.compile(r'(\w+)\.(\d+).(\d+)')
def print_trace(trace, verbose):
    time = datetime.datetime.fromtimestamp(trace.header.time / 1000000000.).strftime(TIME_FORMAT)
    message = c_format_to_python_format(underline_variables(trace.info.format)) % tuple(trace.params)
    location = LOCATION_FORMAT.format(channel=trace.channel,
                                      file=trace.info.file.rsplit('/', 1)[1],
                                      func=term.bold + trace.info.func + term.normal,
                                      line=trace.info.line) if verbose else ''
    print(TRACE_FORMAT.format(time=time,
                              message=message,
                              location=location,
                              component=components.get(trace.info.component, ''),
                              tid=trace.tid,
                              pid=trace.pid,
                              job_id=trace.header.job_id,
                              severity=severities[trace.header.severity]))

def print_error(msg):
    print(term.red + 'READER ERROR: ' + msg + term.normal)

Trace = collections.namedtuple('Trace', ['info', 'header', 'params', 'channel', 'pid', 'tid'])
def handle_path(path):
    assert os.path.exists(path), 'File does not exist: {}'.format(path)
    match = file_re.search(path)
    assert match is not None, 'Not a trace file: {}'.format(path)
    assert os.stat(path).st_size > 0, 'Trace file is empty: {}'.format(path)
    channel, pid, tid = match.groups()
    with open(path, 'rb') as f:
        for info, header, params in get_traces(f, get_trace_info(f)):
            yield Trace(info=info, header=header, params=params, channel=channel, pid=int(pid), tid=int(tid))

def safe_handle_path(path, verbose):
    try:
        yield from handle_path(path)
    except Exception as e:
        if verbose:
            traceback.print_exc()
        print_error('Failed parsing trace file: {}. Error: {}'.format(path, e))

def paths_to_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for f in files:
                    yield os.path.join(root, f)
        else:
            yield path

def run(paths, verbose):
    for path in paths_to_files(paths):
        if verbose:
            print("found {}".format(path))

    for trace in merge_sort([safe_handle_path(path, verbose) for path in paths_to_files(paths)],
                            lambda trace: trace.header.time):
        print_trace(trace, verbose)

@click.command()
@click.argument('paths', nargs=-1)
@click.option('-v', '--verbose', is_flag=True)
@click.option('-d', '--debug', is_flag=True)
def main(paths, verbose, debug):
    try:
        run(paths, verbose)
    except:
        if debug:
            import pdb
            pdb.post_mortem()
        raise

if __name__ == '__main__':
    main()
