cmake_minimum_required(VERSION 3.22)
project(sample_cpp CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Library: graph
add_library(graph graph.cpp graph.h)
target_include_directories(graph PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

# Executable: main
add_executable(sample_app main.cpp)
target_link_libraries(sample_app PRIVATE graph)
