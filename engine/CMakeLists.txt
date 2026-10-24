cmake_minimum_required(VERSION 3.10)

project(matcha)

include(FetchContent)

FetchContent_Declare (
    googletest
    URL https://github.com/google/googletest/releases/download/v1.17.0/googletest-1.17.0.tar.gz
)

FetchContent_MakeAvailable(googletest)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(include)

add_library(matcha_lib
    src/arena.cpp
    src/order_book.cpp
    src/price_level.cpp
)

add_executable(matcha
    src/main.cpp
)

target_link_libraries(matcha
    PRIVATE
    matcha_lib
)

add_executable(matcha_tests
    tests/main.cpp
)

target_link_libraries(matcha_tests
    PRIVATE
    matcha_lib
    GTest::gtest_main
)
