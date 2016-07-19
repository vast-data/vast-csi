import pytest
from vproto.parser import *
from vproto.main import *

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
    assert gender_enum == Enum(name=Name(value='Gender'),
                               values=[EnumValue(name=Name(value='MALE'), value=Number(value=0)),
                                       EnumValue(name=Name(value='FEMALE'), value=None)], type=Name(value='byte'))
    assert profession_enum == Enum(name=Name(value='Profession'),
                                   values=[EnumValue(name=Name(value='JANITOR'), value=None),
                                           EnumValue(name=Name(value='PILOT'), value=None)], type=None)
    assert person_struct == Struct(name=Name(value='Person'),
                                   fields=[Field(name=Name(value='name'),
                                                 index=Number(value=0),
                                                 type=FieldType(name=Name(value='char'), elements=Number(value=128)),
                                                 default=None),
                                           Field(name=Name(value='age'),
                                                 index=Number(value=1),
                                                 type=FieldType(name=Name(value='uint32_t'), elements=None),
                                                 default=None),
                                           Field(name=Name(value='active'),
                                                 index=Number(value=2),
                                                 type=FieldType(name=Name(value='bool'), elements=None),
                                                 default=Bool(value='true')),
                                           Field(name=Name(value='profession'),
                                                 index=Number(value=3),
                                                 type=FieldType(name=Name(value='Profession'), elements=None),
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
