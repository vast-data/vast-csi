import pytest
from vproto.parser import *
from vproto.main import *
from vproto.struct import *

def test_parser():
    gender_enum, profession_enum, person_struct = parse('''
enum Gender : byte {
  MALE = 0,
  FEMALE
};

enum Profession {
  JANITOR,
  PILOT
};

struct Person {
  @0 name char[128];
  @1 age uint32_t;
  @2 active bool = true;
  @3 profession Profession = PILOT;
};
''')
    assert gender_enum == Enum(name='Gender',
                               values=[EnumValue(name='MALE', value=Number(value=0)),
                                       EnumValue(name='FEMALE', value=None)], type='byte')
    assert profession_enum == Enum(name='Profession',
                                   values=[EnumValue(name='JANITOR', value=None),
                                           EnumValue(name='PILOT', value=None)], type=None)
    assert person_struct == Struct(name='Person',
                                   fields=[Field(name='name',
                                                 index=0,
                                                 type=FieldType(name='char', elements=128),
                                                 default=None),
                                           Field(name='age',
                                                 index=1,
                                                 type=FieldType(name='uint32_t', elements=None),
                                                 default=None),
                                           Field(name='active',
                                                 index=2,
                                                 type=FieldType(name='bool', elements=None),
                                                 default=Bool(value='true')),
                                           Field(name='profession',
                                                 index=3,
                                                 type=FieldType(name='Profession', elements=None),
                                                 default=Name(value='PILOT'))])

def test_struct_default_validation():
    struct, = parse('''
struct Person {
  @0 name char[128] = 0;
};
''')
    with pytest.raises(SchemaError):
        validate_struct(struct)

def test_struct_fields_validation():
    struct, = parse('''
struct Person {
  @1 age uint32_t;
};
''')
    with pytest.raises(SchemaError):
        validate_struct(struct)

    struct, = parse('''
struct Person {
  @0 age uint32_t;
  @2 weight uint32_t;
};
''')
    with pytest.raises(SchemaError):
        validate_struct(struct)

        struct, = parse('''
struct Person {
  @0 age uint32_t;
  @1 age uint32_t;
};
''')
    with pytest.raises(SchemaError):
        validate_struct(struct)

def fields_names(fields):
    return [i.name if hasattr(i, 'name') else i.size for i in fields]

def fields_offsets(fields):
    return [i.offset for i in fields]

def test_align_fields():
    f1 = Field(name='f1', index=0, default=None,
               type=FieldType(name='uint8_t', elements=None))
    f2 = Field(name='f2', index=1, default=None,
               type=FieldType(name='uint8_t', elements=None))
    fields = align_fields([f2, f1])
    assert fields_names(fields) == ['f1', 'f2']

    f1 = Field(name='f1', index=0, default=None,
               type=FieldType(name='uint8_t', elements=None))
    f2 = Field(name='f2', index=0, default=None,
               type=FieldType(name='uint16_t', elements=None))
    fields = align_fields([f1, f2])
    assert fields_names(fields) == ['f1', 1, 'f2']

    f1 = Field(name='f1', index=0, default=None,
               type=FieldType(name='uint8_t', elements=None))
    f2 = Field(name='f2', index=0, default=None,
               type=FieldType(name='uint32_t', elements=None))
    fields = align_fields([f1, f2])
    assert fields_names(fields) == ['f1', 3, 'f2']

    f1 = Field(name='f1', index=0, default=None,
               type=FieldType(name='uint8_t', elements=None))
    f2 = Field(name='f2', index=0, default=None,
               type=FieldType(name='uint32_t', elements=None))
    f3 = Field(name='f3', index=0, default=None,
               type=FieldType(name='uint16_t', elements=None))
    fields = align_fields([f1, f2, f3])
    assert fields_names(fields) == ['f1', 1, 'f3', 'f2']

    f1 = Field(name='f1', index=0, default=None,
               type=FieldType(name='uint8_t', elements=None))
    f2 = Field(name='f2', index=0, default=None,
               type=FieldType(name='uint64_t', elements=None))
    f3 = Field(name='f3', index=0, default=None,
               type=FieldType(name='uint16_t', elements=None))
    f4 = Field(name='f4', index=0, default=None,
               type=FieldType(name='uint32_t', elements=None))
    f5 = Field(name='f5', index=0, default=None,
               type=FieldType(name='uint8_t', elements=None))
    fields = align_fields([f1, f2, f3, f4, f5])
    assert fields_names(fields) == ['f1', 'f5', 'f3', 'f4', 'f2']
    assert fields_offsets(fields) == [0, 1, 2, 4, 8]

def test_struct_size():
    struct, = parse('''
struct Person {
  @0 age uint32_t;
  @1 height uint16_t;
};
''')
    assert VProtoStruct(struct).size == 8

    struct, = parse('''
struct Person {
  @0 first char[16];
  @1 last char[12];
};
''')
    assert VProtoStruct(struct).size == 48

    struct, = parse('''
struct Person {
  @0 first char[12];
  @1 last char[16];
};
''')
    assert VProtoStruct(struct).size == 48
