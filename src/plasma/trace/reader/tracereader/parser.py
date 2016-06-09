"""Copyright (C) Vast Data Ltd."""

import re
import ctypes
import struct
import collections

TraceInfo = collections.namedtuple('TraceInfo', ['format', 'file', 'func', 'line'])
trace_info_struct = struct.Struct('128s64s54sH8x')
assert trace_info_struct.size == 256

TraceHeader = collections.namedtuple('TraceHeader', ['time', 'job_id', 'info_index', 'severity'])
trace_header_struct = struct.Struct('QIHB')

def bytes_to_string(b):
    s = b.decode('utf-8')
    return s[:s.index('\x00')]

def get_trace_info(stream):
    version, = struct.unpack('H', stream.read(2))
    count, = struct.unpack('H', stream.read(2))
    for i in range(count):
        fields = trace_info_struct.unpack(stream.read(trace_info_struct.size))
        yield TraceInfo._make(bytes_to_string(i) if isinstance(i, bytes) else i for i in fields)

CHUNK_SIZE = 2**20
RECORD_LENGTH_TYPE = 'H'
RECORD_LENGTH_SIZE = 2
def get_traces_header_and_data(stream):
    while True:
        bytes_left_in_chunk = CHUNK_SIZE
        while bytes_left_in_chunk > 0:
            length_data = stream.read(RECORD_LENGTH_SIZE)
            if length_data == b'':
                return
            length, = struct.unpack(RECORD_LENGTH_TYPE, length_data)
            bytes_left_in_chunk -= RECORD_LENGTH_SIZE
            if length == 0:
                padding = stream.read(bytes_left_in_chunk)
                assert padding == len(padding) * b'\x00', 'Found data within the padding: (length: {}) {}{}'.format(len(padding), padding[:100], '...' if len(padding) > 0 else '')
                break

            header_data = stream.read(trace_header_struct.size)
            params_data = stream.read(length - trace_header_struct.size)
            assert len(params_data) + len(header_data) == length, 'Expected {}. Got {} + {}'.format(length, len(params_data), len(header_data))

            header = TraceHeader._make(trace_header_struct.unpack(header_data))
            yield header, params_data

            bytes_left_in_chunk -= length
            if (bytes_left_in_chunk < 0):
                assert bytes_left_in_chunk >= 0, 'Overflow from chunk size {} with length {}'.format(bytes_left_in_chunk, length)

                # we need to extract the length and type of each specifier
printf_format_re = re.compile('''\
%                                  # literal %
(?:[-+0 #]{0,5})                   # optional flags
(?:\d+|\*)?                        # width
(?:\.(?:\d+|\*))?                  # precision
(hh|h|l|ll|j|z|t)?                 # capture the length
([cdiouxXeEfgGaAps])               # capture the type
''', re.VERBOSE)

def get_traces(stream, trace_infos):
    trace_infos = list(trace_infos)
    for header, params_data in get_traces_header_and_data(stream):
        info = trace_infos[header.info_index]
        params = parse_params(info.format, params_data)
        yield info, header, params

# the following info is extracted from here: http://www.cplusplus.com/reference/cstdio/printf/
# we interpret chars as single bytes in order to be able to pass bools as a single byte and have them printed.
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
    specifier_map['hh' + unsigned_specifier] = ctypes.c_ubyte
    specifier_map['h' + unsigned_specifier] = ctypes.c_ushort
    specifier_map['l' + unsigned_specifier] = ctypes.c_ulong
    specifier_map['ll' + unsigned_specifier] = ctypes.c_ulonglong
    specifier_map['j' + unsigned_specifier] = ctypes.c_ulonglong
    specifier_map['z' + unsigned_specifier] = ctypes.c_longlong # size_t
    specifier_map['t' + unsigned_specifier] = ctypes.c_longlong # ptrdiff_t
for float_specifier in 'fFeEgGaA':
    for length_specifier, dtype in [('', ctypes.c_float), ('l', ctypes.c_double)]:
        specifier_map[length_specifier + float_specifier] = dtype

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
                  ctypes.c_float: 'f',
                  ctypes.c_double: 'd',
                  ctypes.c_void_p: 'P'}

# validate all specifier are handled and there are now data types that have no specifiers
missing = set(specifier_map.values()).symmetric_difference(dtype_to_field)
assert not missing, missing
del missing

STR_LENGTH_TYPE = 'H'
STR_LENGTH_SIZE = 2
def parse_params(format, buffer):
    pos = 0
    params = []
    for (length, type) in printf_format_re.findall(format):
        specifier = length + type
        if specifier == 's':
            size, = struct.unpack(STR_LENGTH_TYPE, buffer[pos:pos + STR_LENGTH_SIZE])
            pos += STR_LENGTH_SIZE
            params.append(buffer[pos:pos + size].decode('utf-8'))
            pos += size
        else:
            dtype = specifier_map[specifier]
            dtype_size = ctypes.sizeof(dtype)
            part = buffer[pos:pos + dtype_size]
            assert len(part) == dtype_size, 'Format string expects more data ({}) than received ({}): {}'.format(dtype_size, len(part), format)
            params.append(struct.unpack(dtype_to_field[dtype], part)[0])
            pos += dtype_size
    assert len(buffer) == pos, 'Format string "{}" did not consume all params. Expected {} bytes and got {} instead.'.format(format, pos, len(buffer))
    return params
