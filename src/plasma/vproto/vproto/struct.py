from collections import namedtuple, OrderedDict, Counter
from .parser import Field, FieldType

class SchemaError(Exception): pass

VProtoType = namedtuple('VProtoType', ['name', 'size', 'is_primitive'])

class TypeRegistry(object):
    def __init__(self):
        self.types = {}

        # add builtin types
        self.add(VProtoType('bool', 1, True))
        self.add(VProtoType('char', 1, True))
        self.add(VProtoType('int8_t', 1, True))
        self.add(VProtoType('uint8_t', 1, True))
        self.add(VProtoType('int16_t', 2, True))
        self.add(VProtoType('uint16_t', 2, True))
        self.add(VProtoType('int32_t', 4, True))
        self.add(VProtoType('uint32_t', 4, True))
        self.add(VProtoType('int64_t', 8, True))
        self.add(VProtoType('uint64_t', 8, True))
        self.add(VProtoType('float', 4, True))
        self.add(VProtoType('double', 8, True))

        # vast types
        self.add(VProtoType('byte', 1, True))
        self.add(VProtoType('P::Index', 4, True))

        # vproto
        self.add(VProtoType('P::VProto::ArrayPtr', 8, True))

    def get(self, name):
        try:
            return self.types[name]
        except KeyError:
            raise Exception('Unknown field type: {}'.format(name))

    def add(self, type):
        self.types[type.name] = type

    def add_struct(self, struct):
        self.add(struct)

    def add_enum(self, enum):
        self.add(VProtoType(enum.name, 4 if enum.type is None else self.get(enum.type).size, True))

Padding = namedtuple('Padding', ['size', 'offset'])
VProtoField = namedtuple('VProtoField', ['name', 'index', 'type', 'elements', 'default', 'offset'])

def align_fields(fields, registry=TypeRegistry()):
    '''Align fields in a backward compatible order (first by index, then fill padding where possible)'''
    offset = 0
    result = []
    for field in sorted(fields, key=lambda field: field.index):
        field_type = registry.get(field.type.name)
        field_size = field_type.size
        # find the smallest padding we can fit this field into
        padding_index = None
        for index, thing in enumerate(result):
            if isinstance(thing, Padding):
                if thing.size >= field_size and (padding_index == None or thing.size < result[padding_index].size):
                    padding_index = index

        if padding_index is not None:
            # replace the padding with the field and new padding if necessary
            padding = result.pop(padding_index)
            pre_padding_size = 0
            if padding.offset % field_size > 0:
                pre_padding_size = field_size - padding.offset % field_size
                result.insert(padding_index, Padding(pre_padding_size, padding.offset))
                padding_index += 1
            result.insert(padding_index, VProtoField(name=field.name, index=field.index, type=field_type,
                                                     elements=field.type.elements, default=field.default,
                                                     offset=padding.offset + pre_padding_size))
            leftover = padding.size - pre_padding_size - field_size
            if leftover:
                result.insert(padding_index + 1, Padding(size=leftover, offset=padding.offset + pre_padding_size + field_size))
        else:
            # append the field in the end
            if offset % field_size > 0:
                padding_size = field_size - offset % field_size
                result.append(Padding(size=padding_size, offset=offset))
                offset += padding_size
            result.append(VProtoField(name=field.name, index=field.index, type=field_type,
                                      elements=field.type.elements, default=field.default,
                                      offset=offset))
            offset += field_size
    return result

def field_is_primitive(field, registry):
    return field.type.elements is None and registry.get(field.type.name).is_primitive

class VProtoStruct(object):
    def __init__(self, struct_ast, registry=TypeRegistry()):
        validate_struct(struct_ast, registry)
        self.is_primitive = False
        self.name = struct_ast.name
        self.largest_field = 0

        variable_fields = []
        primitive_fields = []
        for field in struct_ast.fields:
            if not field_is_primitive(field, registry):
                variable_fields.append(field)
                field = Field(name=field.name + '_ptr', index=field.index, default=None,
                              type=FieldType(name='P::VProto::ArrayPtr', elements=None))
            primitive_fields.append(field)
            self.largest_field = max(self.largest_field, registry.get(field.type.name).size)

        self.primitive_fields = [i for i in align_fields(primitive_fields, registry) if not isinstance(i, Padding)]
        self.last_index = self.primitive_fields[-1].index


        self.variable_fields = []
        self.size = self.primitive_fields[-1].offset + self.primitive_fields[-1].type.size
        for field in variable_fields:
            field_type = registry.get(field.type.name)
            largest_field = field_type.size if field_type.is_primitive else field_type.largest_field
            padding = 0
            if self.size % largest_field > 0:
                padding = largest_field - self.size % largest_field
            self.variable_fields.append(VProtoField(name=field.name, index=field.index,
                                                    type=field_type, elements=field.type.elements,
                                                    default=None, offset=self.size + padding))
            self.size += field_type.size * (1 if field.type.elements is None else field.type.elements)
            # each variable length field should be aligned on the size of its largest member.
            self.largest_field = max(self.largest_field, largest_field)

        # the entire struct should be aligned on the size of its largest member (simplifies array stride)
        if self.size % self.largest_field > 0:
            self.size += self.largest_field - self.size % self.largest_field
        registry.add_struct(self)

def validate_struct(struct, registry=TypeRegistry()):
    indices = []
    names = []
    for field in struct.fields:
        indices.append(field.index)
        names.append(field.name)
        if field.default is not None and not field_is_primitive(field, registry):
            raise SchemaError('Array/Struct fields cannot have default values: {}.{}'.format(struct.name, field.name))

    indices.sort()
    missing = set(range(indices[-1])) - set(indices)
    if missing:
        raise SchemaError('Struct {} is missing indices: {}'.format(struct.name, ', '.join(map(str, missing))))

    for name, count in Counter(names).items():
        if count > 1:
            raise SchemaError('Field cannot be repeated within a struct: {}.{}'.format(struct.name, name))
