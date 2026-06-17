cmake_minimum_required(VERSION 3.22)
project(sample_cpp_ns CXX)

# Require C++17 standard for modern features (like emplace_back, std::string tracking, etc.)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Library: graph
add_library(graph graph.cpp graph.h)
target_include_directories(graph PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

# Executable: main
add_executable(sample_app_ns main.cpp)
target_link_libraries(sample_app_ns PRIVATE graph)
