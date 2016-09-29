cmake_minimum_required(VERSION 3.5)
project(orion)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++11 -D_GNU_SOURCE -D__USE_BSD -D__STDC_LIMIT_MACROS")

include_directories(BEFORE SYSTEM ../linux_inc)
include_directories(src tests)

file(GLOB_RECURSE SOURCE_FILES *.cpp *.hpp *.c *.h)
add_executable(orion ${SOURCE_FILES})

set(DUMMY_SRC dummy_main.c)
add_executable(dummy ${DUMMY_SRC})
add_custom_target(RerunCmake ${CMAKE_COMMAND} ${CMAKE_SOURCE_DIR})
add_dependencies(dummy RerunCmake)

add_custom_command(
    TARGET RerunCmake
    COMMAND vagrant ssh -c "cd orion ; scons debug=1 -j 4 2>&1 | sed \"s#build/debug/##g\" | sed \"s#/usr/include/#../linux_inc/#g\" | sed \"s#`pwd`/##g\""
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Running remote build"
    VERBATIM
    )