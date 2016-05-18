/*!
 * The macro_is_set was found here: http://stackoverflow.com/questions/5464170/using-definedmacro-inside-the-c-if-statement
 */
#define MACRO_IS_SET(macro) MACRO_IS_SET_(macro)
#define MACROTEST_1 ,
#define MACRO_IS_SET_(value) MACRO_IS_SET__(MACROTEST_##value)
#define MACRO_IS_SET__(comma) MACRO_IS_SET___(comma 1, 0)
#define MACRO_IS_SET___(_, v, ...) v

/*!
 * The following macro magic is copied from https://codecraft.co/2014/11/25/variadic-macros-tricks/
 */
#define _GET_NTH_ARG(_1, _2, _3, _4, _5, _6, _7, _8, N, ...) N

#define _fe_0(_call, ...)
#define _fe_1(_call, x) _call(x)
#define _fe_2(_call, x, ...) _call(x) _fe_1(_call, __VA_ARGS__)
#define _fe_3(_call, x, ...) _call(x) _fe_2(_call, __VA_ARGS__)
#define _fe_4(_call, x, ...) _call(x) _fe_3(_call, __VA_ARGS__)
#define _fe_5(_call, x, ...) _call(x) _fe_4(_call, __VA_ARGS__)
#define _fe_6(_call, x, ...) _call(x) _fe_5(_call, __VA_ARGS__)
#define _fe_7(_call, x, ...) _call(x) _fe_6(_call, __VA_ARGS__)

/*!
 * Provide a for-each construct for variadic macros. Supports up
 * to 8 args.
 *
 * Example usage1:
 *     #define FWD_DECLARE_CLASS(cls) class cls;
 *     CALL_MACRO_X_FOR_EACH(FWD_DECLARE_CLASS, Foo, Bar)
 */
#define CALL_MACRO_X_FOR_EACH(x, ...)                                   \
    _GET_NTH_ARG("ignored", ##__VA_ARGS__,                              \
                 _fe7, _fe_6, _fe_5, _fe_4, _fe_3, _fe_2, _fe_1, _fe_0)(x, ##__VA_ARGS__)

/*!
 * The following macros provide a template for creating an enum
 * Along with helper functions that convert between enum values and strings.
 */
#define DEFINE_LOOKUP_ID(x) x
#define DEFINE_LOOKUP_PROTOTYPES(list, name, id_to_string, string_to_id) \
    typedef enum {                                                       \
        list(DEFINE_LOOKUP_ID)                                           \
    } name;                                                              \
    const char *id_to_string(name id);                                   \
    name string_to_id(const char *string);

#define DEFINE_LOOKUP_STRING(x) #x
#define DEFINE_LOOKUP_IMPLEMENTATION(list, name, array, id_to_string, string_to_id) \
    static const char *array[] = {                                      \
        list(DEFINE_LOOKUP_STRING),                                     \
        NULL                                                            \
    };                                                                  \
    const char *id_to_string(name id)                                   \
    {                                                                   \
        return array[id];                                               \
    }                                                                   \
    name string_to_id(const char *string)                               \
    {                                                                   \
        for (name i = 0; array[i] != NULL; i++)                         \
            if (strcmp(array[i], string) == 0)                          \
                return i;                                               \
        P_PANIC();                                                      \
    }

/*!
 * Use the following macro to easily define multi-line strings.
 */
#define QUOTE(...) #__VA_ARGS__
