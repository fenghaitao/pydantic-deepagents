#!/usr/bin/env bash
# Generate compile_commands.json for scip-clang / clangd.
#
# Usage:
#   ./gen-compile-commands.sh            # Release (default)
#   ./gen-compile-commands.sh Debug      # Debug build

set -euo pipefail

BUILD_TYPE="${1:-Release}"
BUILD_DIR="linux64/bt-${BUILD_TYPE,,}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use Intel GCC 12.1.0 explicitly (matches the version on both development and
# CI machines).  Fall back to the system g++/gcc if the package is not present.
GCC12=/usr/intel/pkgs/gcc/12.1.0/bin
if [[ -x "${GCC12}/g++" ]]; then
    CXX_COMPILER="${GCC12}/g++"
    CC_COMPILER="${GCC12}/gcc"
else
    CXX_COMPILER=$(command -v g++ || command -v clang++)
    CC_COMPILER=$(command -v gcc || command -v clang)
fi
echo "Using compiler: ${CXX_COMPILER} ($(${CXX_COMPILER} --version 2>&1 | head -1))"

echo "--- Configuring (${BUILD_TYPE}) ---"
cmake -S . -B "${BUILD_DIR}" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DCMAKE_C_COMPILER="${CC_COMPILER}" \
    -DCMAKE_CXX_COMPILER="${CXX_COMPILER}"

echo "--- Building ---"
cmake --build "${BUILD_DIR}" --target all

echo "--- Copying compile_commands.json ---"
cp "${BUILD_DIR}/compile_commands.json" compile_commands.json

echo "Done. compile_commands.json is ready."
