#!/bin/bash
# gen-compile-commands.sh — Configure CMake and regenerate compile_commands.json.
#
# Usage:  bash gen-compile-commands.sh [CXX_COMPILER]
#
# scip-clang reads compile_commands.json only for flags (include paths, -std=,
# defines) — it never invokes the compiler listed there. Any C++ compiler works.
# Defaults to g++ if available, otherwise clang++.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve compiler: explicit arg > g++ > clang++
if [[ $# -ge 1 ]]; then
  CLANGPP="$1"
elif command -v g++ &>/dev/null; then
  CLANGPP=g++
elif command -v clang++ &>/dev/null; then
  CLANGPP=clang++
else
  echo "ERROR: no C++ compiler found (tried g++, clang++). Pass one as an argument." >&2
  exit 1
fi

echo "Configuring CMake with $CLANGPP ($($CLANGPP --version 2>/dev/null | head -1)) ..."

cmake -S "$SCRIPT_DIR" -B "$SCRIPT_DIR/build" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DCMAKE_CXX_COMPILER="$CLANGPP"

cp "$SCRIPT_DIR/build/compile_commands.json" "$SCRIPT_DIR/compile_commands.json"

echo "Done. compile_commands.json written to $SCRIPT_DIR/compile_commands.json"
