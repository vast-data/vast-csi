import re
import sys
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
              1: term.green + 'DEBUG' + term.normal,
              2: term.cyan + 'INFO' + term.normal,
              3: term.yellow + 'WARN' + term.normal,
              4: term.red + 'ERROR' + term.normal}

TIME_FORMAT = '%y/%m/%d %H:%M:%S.%f'
TRACE_FORMAT = '{time} ({tid}|{job_id}) [{component}] {severity}: {message}'
file_re = re.compile(r'(\w+)\.(\d+)')
def print_trace(trace):
    time = datetime.datetime.fromtimestamp(trace.header.time / 1000000000.).strftime(TIME_FORMAT)
    message = c_format_to_python_format(underline_variables(trace.info.format)) % tuple(trace.params)
    print(TRACE_FORMAT.format(time=time, tid=trace.tid, component=trace.component, message=message,
                              job_id=trace.header.job_id, severity=severities[trace.header.severity]))

Trace = collections.namedtuple('Trace', ['info', 'header', 'params', 'component', 'tid'])
def handle_path(path):
    match = file_re.search(path)
    assert match is not None, 'Not a trace file: {}'.format(path)
    component, tid = match.groups()
    with open(path, 'rb') as f:
        for info, header, params in get_traces(f, get_trace_info(f)):
            yield Trace(info=info, header=header, params=params, component=component, tid=tid)

def run(paths):
    paths = sys.argv[1:]
    for trace in merge_sort(map(handle_path, paths), lambda trace: trace.header.time):
        print_trace(trace)

def main():
    run(sys.argv[1:])

if __name__ == '__main__':
    main()
