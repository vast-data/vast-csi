from ply import lex, yacc
from collections import namedtuple

DEBUG = False

Name = namedtuple('Name', ['value'])
Number = namedtuple('Number', ['value'])
Bool = namedtuple('Bool', ['value'])
FieldType = namedtuple('FieldType', ['name', 'elements'])
Field = namedtuple('Field', ['name', 'index', 'type', 'default'])
Struct = namedtuple('Struct', ['name', 'fields'])
Enum = namedtuple('Enum', ['name', 'values', 'type'])
EnumValue = namedtuple('EnumValue', ['name', 'value'])
Directive = namedtuple('Directive', ['value'])

class ParseError(Exception): pass
class LexError(Exception): pass

def get_relative_column(absolute_column):
    last_cr = lexer.lexdata.rfind('\n', 0, absolute_column)
    if last_cr < 0:
        last_cr = -1
    return absolute_column - (last_cr + 1)

reserved = ['struct', 'enum', 'true', 'false']

tokens = [
    'NUMBER',
    'DIRECTIVE',
    'NAME',
] + [i.upper() for i in reserved]

literals = '{}[]@:=;,$'
t_ignore  = ' \t'

def t_newline(t):
    r'\n+'
    t.lexer.lineno += len(t.value)

def t_NUMBER(t):
    r'[0-9]+'
    t.value = Number(value=int(t.value))
    return t

def t_DIRECTIVE(t):
    r'\$.+'
    t.value = Directive(value=t.value[1:])
    return t

def t_NAME(t):
    r'[a-zA-Z][a-zA-Z0-9:_]*'
    if t.value not in reserved:
        t.value = Name(value=t.value)
    else:
        t.type = t.value.upper()
    return t

def t_error(t):
    raise LexError('Error occured during parsing: {}'.format(t))

lexer = lex.lex(debug=DEBUG)

def p_definitions_multiple(p):
    r'definitions : definitions definition'
    p[0] = p[1] + [p[2]]

def p_definitions_single(p):
    r'definitions : definition'
    p[0] = [p[1]]

def p_definition(p):
    r'''definition : struct
                   | enum
                   | DIRECTIVE'''
    p[0] = p[1]

def p_struct(p):
    r'struct : STRUCT NAME "{" struct_fields "}" ";"'
    p[0] = Struct(name=p[2], fields=p[4])

def p_struct_empty(p):
    r'struct : STRUCT NAME "{" "}" ";"'
    p[0] = Struct(name=p[2], fields=[])

def p_fields_multiple(p):
    r'struct_fields : struct_fields struct_field'
    p[0] = p[1] + [p[2]]

def p_fields_single(p):
    r'struct_fields : struct_field'
    p[0] = [p[1]]

def p_field(p):
    r'struct_field : "@" NUMBER NAME field_type ";"'
    p[0] = Field(index=p[2], name=p[3], type=p[4], default=None)

def p_field_default(p):
    r'struct_field : "@" NUMBER NAME field_type "=" value ";"'
    p[0] = Field(index=p[2], name=p[3], type=p[4], default=p[6])

def p_field_type(p):
    r'field_type : NAME'
    p[0] = FieldType(name=p[1], elements=None)

def p_field_type_array(p):
    r'field_type : NAME "[" NUMBER "]"'
    p[0] = FieldType(name=p[1], elements=p[3])

def p_enum_type(p):
    r'enum : ENUM NAME ":" NAME "{" enum_values "}" ";"'
    p[0] = Enum(name=p[2], values=p[6], type=p[4])

def p_enum(p):
    r'enum : ENUM NAME "{" enum_values "}" ";"'
    p[0] = Enum(name=p[2], values=p[4], type=None)

def p_enum_values_multiple(p):
    r'enum_values : enum_values "," enum_value'
    p[0] = p[1] + [p[3]]

def p_enum_values_single(p):
    r'enum_values : enum_value'
    p[0] = [p[1]]

def p_enum_value(p):
    r'enum_value : NAME'
    p[0] = EnumValue(name=p[1], value=None)

def p_enum_value_value(p):
    r'enum_value : NAME "=" value'
    p[0] = EnumValue(name=p[1], value=p[3])

def p_bool(p):
    r'''bool : TRUE
             | FALSE'''
    p[0] = Bool(value=p[1])

def p_value(p):
    r'''value : NUMBER
              | bool
              | NAME'''
    p[0] = p[1]

def p_error(p):
    if p is None:
        raise ParseError('Unexpected end of input')
    raise ParseError("Unexpected token '{}' at line {} position {}".format(p.value, p.lineno, get_relative_column(p.lexpos)))

parser = yacc.yacc()

def parse(string):
    lexer.lineno = 1; # makes parsing not thread-safe
    return parser.parse(string, debug=DEBUG, tracking=True)
