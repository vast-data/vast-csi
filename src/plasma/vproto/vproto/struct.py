from collections import namedtuple, OrderedDict, Counter
from .parser import Field, FieldType, Name, Number

MAX_STRUCT_FIELDS = 2**8
MAX_STRUCT_SIZE = 2**20
MAX_ARRAY_ELEMENTS = 2**16

class SchemaError(Exception): pass

VProtoType = namedtuple('VProtoType', ['name', 'size', 'alignment', 'is_primitive', 'module'])

class VProtoBuiltinsModule(object):
    def get_namespace(self):
        return 'P'
vproto_builtins_module = VProtoBuiltinsModule()

class BuiltinsModule(object):
    def get_namespace(self):
        return ''
builtins_module = BuiltinsModule()

class TypeRegistry(object):
    BUILTINS = {'bool': 1,
                'char': 1,
                'int8_t': 1,
                'uint8_t': 1,
                'int16_t': 2,
                'uint16_t': 2,
                'int32_t': 4,
                'uint32_t': 4,
                'int64_t': 8,
                'uint64_t': 8,
                'float': 4,
                'double': 8}
    VPROTO_BUILTINS = [VProtoType('byte', 1, 1, True, vproto_builtins_module),
                       VProtoType('Index', 4, 4, True, vproto_builtins_module),
                       VProtoType('GUID', 16, 8, True, vproto_builtins_module),
                       VProtoType('VProto::ArrayPtr', 8, 8, True, vproto_builtins_module)]
    BUILTINS_NAMES = list(BUILTINS.keys()) + [i.name for i in VPROTO_BUILTINS]

    def __init__(self):
        self._types = {}
        self._aliases = {}
        self._consts = {}

        for name, size in self.BUILTINS.items():
            self.add(VProtoType(name, size, size, True, builtins_module))
        for builtin in self.VPROTO_BUILTINS:
            self.add(builtin)

    def get(self, name):
        try:
            return self._types[name]
        except KeyError:
            try:
                return self._types[self._aliases[name]]
            except KeyError:
                raise SchemaError('Unknown field type: {}'.format(name))

    def add(self, type):
        self._types[type.name] = type

    def add_alias(self, type_name, alias):
        self._aliases[alias] = type_name

    def add_const(self, name, type, value):
        self._consts[name] = (type, value)

    def get_const_value(self, name):
        try:
            return self._consts[name][1]
        except KeyError:
            raise SchemaError('Unknown const name: {}'.format(name))

    def add_struct(self, struct):
        self.add(struct)

    DEFAULT_ENUM_SIZE = 4
    def add_enum(self, enum):
        size = self.DEFAULT_ENUM_SIZE if enum.type is None else enum.type.size
        self.add(VProtoType(enum.name, size, size, True, enum.module))

    def merge(self, registry, alias=None):
        prefix = '' if alias is None else alias + '.'
        for name, type in registry._types.items():
            if name not in self.BUILTINS_NAMES:
                self._types[prefix + name] = type
        for type_alias, type_name in registry._aliases.items():
            self._aliases[prefix + type_alias] = type_name
        for (name, (type,value)) in registry._consts.items():
            self._consts[prefix + name] = (type, value)

Padding = namedtuple('Padding', ['size', 'offset'])
VProtoField = namedtuple('VProtoField', ['name', 'index', 'type', 'elements', 'default', 'offset'])

def align_fields(fields, registry=TypeRegistry()):
    '''Align fields in a backward compatible order (first by index, then fill padding where possible)'''
    offset = 0
    result = []
    for field in sorted(fields, key=lambda field: field.index):
        field_type = registry.get(field.type.name)
        field_size = field_type.size
        alignment = field_type.alignment
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
            if padding.offset % alignment > 0:
                pre_padding_size = alignment - padding.offset % alignment
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
            if offset % alignment > 0:
                padding_size = alignment - offset % alignment
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
    def __init__(self, struct_ast, module=None, registry=TypeRegistry()):
        validate_struct(struct_ast, registry)
        self.module = module
        self.name = struct_ast.name
        self.is_primitive = False
        self.alignment = 0

        variable_fields = []
        primitive_fields = []
        for field in struct_ast.fields:
            if not field_is_primitive(field, registry):
                variable_fields.append(field)
                field = Field(name=field.name + '_ptr', index=field.index, default=None,
                              type=FieldType(name='VProto::ArrayPtr', elements=None))
            primitive_fields.append(field)
            self.alignment = max(self.alignment, registry.get(field.type.name).alignment)

        self.primitive_fields = [i for i in align_fields(primitive_fields, registry) if not isinstance(i, Padding)]
        if self.primitive_fields:
            self.next_index = max(field.index for field in self.primitive_fields) + 1
            self.size = self.primitive_fields[-1].offset + self.primitive_fields[-1].type.size
        else:
            self.next_index = 0
            self.size = 0

        self.variable_fields = []

        for field in variable_fields:
            field_type = registry.get(field.type.name)
            alignment = field_type.alignment
            padding = 0
            if alignment > 0 and self.size % alignment > 0:
                padding = alignment - self.size % alignment

            elements = field.type.elements
            if elements is not None:
                if isinstance(elements, Name):
                    elements = registry.get_const_value(elements.value)
                    if not elements.isdigit():
                        raise SchemaError('Array size constant should be a number: {}.{}'.format(self.name, field.name))
                    elements = int(elements)
                elif isinstance(elements, Number):
                    elements = elements.value
                else:
                    raise SchemaError('Array size should be a number or a name of constant: {}.{}'.format(self.name, field.name))
                if elements > MAX_ARRAY_ELEMENTS:
                    raise SchemaError('Array {}.{} has too many elements (max={}): {}'.format(self.name, self.name, MAX_ARRAY_ELEMENTS, elements))
            self.variable_fields.append(VProtoField(name=field.name, index=field.index,
                                                    type=field_type, elements=elements,
                                                    default=None, offset=self.size + padding))
            if field_type.size == 0:
                raise SchemaError('Field cannot be of size 0: {}.{}'.format(self.name, field.name))
            self.size += field_type.size * (1 if elements is None else elements)
            # each variable length field should be aligned on the size of its largest member.
            self.alignment = max(self.alignment, alignment)

        # the entire struct should be aligned on the size of its largest member (simplifies array stride)
        if self.size > 0 and self.size % self.alignment > 0:
            self.size += self.alignment - self.size % self.alignment

        if self.size > MAX_STRUCT_SIZE:
            raise SchemaError('Struct {} is larger than allowed maximum ({}): {}'.format(self.name, MAX_STRUCT_SIZE, self.size))
        registry.add_struct(self)

def validate_struct(struct, registry=TypeRegistry()):
    indices = []
    names = []
    for field in struct.fields:
        indices.append(field.index)
        names.append(field.name)
        if field.default is not None and not field_is_primitive(field, registry):
            raise SchemaError('Array/Struct fields cannot have default values: {}.{}'.format(struct.name, field.name))

    if indices:
        indices.sort()
        missing = set(range(indices[-1])) - set(indices)
        if missing:
            raise SchemaError('Struct {} is missing indices: {}'.format(struct.name, ', '.join(map(str, missing))))

        for name, count in Counter(names).items():
            if count > 1:
                raise SchemaError('Field cannot be repeated within a struct: {}.{}'.format(struct.name, name))

        for index, count in Counter(indices).items():
            if count > 1:
                raise SchemaError('Index cannot be repeated within a struct: {}.{}'.format(struct.name, index))

        if len(indices) > MAX_STRUCT_FIELDS:
            raise SchemaError('Struct {} has an invalid number of fields (maximum is {}): {}'.format(struct.name, MAX_STRUCT_FIELDS, len(indices)))

class VProtoEnum(object):

    def __init__(self, enum_ast, module=None, registry=TypeRegistry()):
        self.module = module
        self.values = enum_ast.values
        self.name = enum_ast.name
        self.type = registry.get(enum_ast.type) if enum_ast.type is not None else None
        registry.add_enum(self)
