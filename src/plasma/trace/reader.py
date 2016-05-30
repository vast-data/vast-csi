import re
import os
import sys
import mmap
import ctypes
import struct
import datetime
import blessings
import collections

CHUNK_SIZE = 2**20

TraceInfo = collections.namedtuple('TraceInfo', ['format', 'file', 'func', 'line'])
trace_info_struct = struct.Struct('128s64s54sH8x')
assert trace_info_struct.size == 256

TraceHeader = collections.namedtuple('TraceHeader', ['time', 'job_id', 'info_index', 'severity'])
trace_header_struct = struct.Struct('QIHB')

def strip_nulls(s):
    return s[:s.index('\x00')]

def get_trace_info(f):
    version, = struct.unpack('H', f.read(2))
    count, = struct.unpack('H', f.read(2))
    for i in xrange(count):
        fields = trace_info_struct.unpack(f.read(trace_info_struct.size))
        yield TraceInfo._make(strip_nulls(i) if isinstance(i, str) else i for i in fields)

def get_traces(f):
    while True:
        bytes_left_in_chunk = CHUNK_SIZE
        while bytes_left_in_chunk > 0:
            length_data = f.read(1)
            if length_data == '':
                return
            length, = struct.unpack('B', length_data)
            bytes_left_in_chunk -= 1
            if length == 0:
                padding = f.read(bytes_left_in_chunk)
                assert padding == len(padding) * '\x00', "Found data within the padding: (length: {}) {}...".format(len(padding), padding[:100].encode('hex'))
                break

            header_data = f.read(trace_header_struct.size)
            params_data = f.read(length - trace_header_struct.size)
            assert len(params_data) + len(header_data) == length, "Expected {}. Got {} + {}".format(length, len(params_data), len(header_data))

            header = TraceHeader._make(trace_header_struct.unpack(header_data))
            yield header, params_data

            bytes_left_in_chunk -= length
            if (bytes_left_in_chunk < 0):
                assert bytes_left_in_chunk >= 0, "Overflow from chunk size {} with length {}".format(bytes_left_in_chunk, length)

# we need to extract the length and type of each specifier
format_re = re.compile('''\
%                                  # literal "%"
(?:[-+0 #]{0,5})                   # optional flags
(?:\d+|\*)?                        # width
(?:\.(?:\d+|\*))?                  # precision
(hh|h|l|ll|j|z|t)?                 # capture the length
([cdiouxXeEfgGaAps])               # capture the type
''', re.VERBOSE)

# the following info is extracted from here: http://www.cplusplus.com/reference/cstdio/printf/
# for some reason printf interprets %c as an integer. we know it's a char.
specifier_map = {'c': ctypes.c_byte, 'p': ctypes.c_void_p}
for int_specifier in 'di':
    specifier_map[int_specifier] = ctypes.c_int
    specifier_map['hh' + int_specifier] = ctypes.c_byte
    specifier_map['h' + int_specifier] = ctypes.c_short
    specifier_map['l' + int_specifier] = ctypes.c_long
    specifier_map['ll' + int_specifier] = ctypes.c_longlong
    specifier_map['j' + int_specifier] = ctypes.c_longlong
    specifier_map['z' + int_specifier] = ctypes.c_longlong # size_t
    specifier_map['t' + int_specifier] = ctypes.c_longlong # ptrdiff_t
for unsigned_specifier in 'uoxX':
    specifier_map[unsigned_specifier] = ctypes.c_uint
    specifier_map['hh' + int_specifier] = ctypes.c_ubyte
    specifier_map['h' + int_specifier] = ctypes.c_ushort
    specifier_map['l' + int_specifier] = ctypes.c_ulong
    specifier_map['ll' + int_specifier] = ctypes.c_ulonglong
    specifier_map['j' + int_specifier] = ctypes.c_ulonglong
    specifier_map['z' + int_specifier] = ctypes.c_longlong # size_t
    specifier_map['t' + int_specifier] = ctypes.c_longlong # ptrdiff_t
for float_specifier in 'fFeEgGaA':
    specifier_map[float_specifier] = ctypes.c_double

dtype_to_field = {ctypes.c_byte: 'b',
                  ctypes.c_ubyte: 'B',
                  ctypes.c_short: 'h',
                  ctypes.c_ushort: 'H',
                  ctypes.c_int: 'i',
                  ctypes.c_uint: 'I',
                  ctypes.c_long: 'l',
                  ctypes.c_ulong: 'L',
                  ctypes.c_longlong: 'q',
                  ctypes.c_ulonglong: 'Q',
                  ctypes.c_double: 'd',
                  ctypes.c_void_p: 'P'}

# validate all specifier are handled and there are now data types that have no specifiers
missing = set(specifier_map.values()).symmetric_difference(dtype_to_field)
assert not missing, missing
del missing

def parse_params(format, buffer):
    pos = 0
    params = []
    for (length, type_) in format_re.findall(format):
        specifier = length + type_
        if specifier == 's':
            size = ord(buffer[pos])
            pos += 1
            params.append(buffer[pos: pos + size])
            pos += size
        else:
            dtype = specifier_map[specifier]
            dtype_size = ctypes.sizeof(dtype)
            params.append(struct.unpack(dtype_to_field[dtype], buffer[pos:pos + dtype_size])[0])
            pos += dtype_size
    return params

def underline_variables(format):
    def on_match(match):
        return term.underline + match.group(0) + term.normal
    return format_re.sub(on_match, format)

term = blessings.Terminal()
TIME_FORMAT = '%y/%m/%d %H:%M:%S.%f'
TRACE_FORMAT = '{time} ({tid}|{job_id}) [{component}] {severity}: {message}'
file_re = re.compile(r'(\w+)\.(\d+)')
severities = {0: term.red + 'DEV' + term.normal,
              1: term.green + 'DEBUG' + term.normal,
              2: term.cyan + 'INFO' + term.normal,
              3: term.yellow + 'WARN' + term.normal,
              4: term.red + 'ERROR' + term.normal}
def handle_path(path):
    component, tid = file_re.findall(path)[0]
    with open(path) as f:
        trace_infos = list(get_trace_info(f))
        for (header, params_data) in get_traces(f):
            info = trace_infos[header.info_index]
            params = parse_params(info.format, params_data)
            time = datetime.datetime.fromtimestamp(header.time / 1000000000.).strftime(TIME_FORMAT)
            format = underline_variables(info.format)
            message = format.replace('%p', '0x%x').replace('%hhd', '%d') % tuple(params)
            yield TRACE_FORMAT.format(time=time, tid=tid, component=component, message=message,
                                      job_id=header.job_id, severity=severities[header.severity])

def main(paths):
    for path in paths:
        print "Opening file:", path
        for trace in handle_path(path):
            print trace

if __name__ == '__main__':
    main(sys.argv[1:])
