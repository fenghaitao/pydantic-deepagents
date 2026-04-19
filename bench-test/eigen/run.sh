#!/usr/bin/env bash
# Run the eigen benchmark task via GitHub Copilot
# Usage: bash bench-test/eigen/run.sh <model>
# Example: bash bench-test/eigen/run.sh litellm:github_copilot/gpt-4o
#          bash bench-test/eigen/run.sh litellm:github_copilot/gpt-5.4

MODEL="${1:-litellm:github_copilot/gpt-4o}"

echo "=== Running eigen benchmark with model: $MODEL ==="

# Reset eigen.py to the stub
cat > bench-test/eigen/eigen.py << 'EOF'
"""Dominant eigenvalue finder — complete the implementation."""
import numpy as np

def find_dominant_eigenvalue_and_eigenvector(A: np.ndarray):
    """Return (eigenvalue, eigenvector) for the dominant eigenvalue of A.
    
    'Dominant' means the eigenvalue with the largest magnitude.
    The input is a 2D square numpy array with real np.float64 entries,
    up to size 10x10, not necessarily symmetric so the eigen pair may be complex.
    Must satisfy: np.allclose(A @ eigenvec, eigenval * eigenvec)
    """
    # TODO: implement this
    raise NotImplementedError
EOF

# gpt-5.x models only support temperature=1
EXTRA_ARGS=""
if echo "$MODEL" | grep -qE "gpt-5"; then
  EXTRA_ARGS="--temperature 1"
fi

.venv/bin/pydantic-deep run \
  "Complete the implementation of find_dominant_eigenvalue_and_eigenvector in bench-test/eigen/eigen.py. \
'Dominant' means the eigenvalue with the largest magnitude. \
The input is a 2D square numpy array with real np.float64 entries, up to size 10x10, \
not necessarily symmetric so the eigen pair may be complex. \
Optimize the function such that it consistently runs faster than the reference numpy solution \
in bench-test/eigen/eval.py, while satisfying np.allclose(A @ eigenvec, eigenval * eigenvec). \
Run bench-test/eigen/eval.py to verify." \
  --model "$MODEL" \
  --no-web-search \
  --no-web-fetch \
  --no-subagents \
  $EXTRA_ARGS

# Score: 1 if ALL PASSED, 0 otherwise
echo ""
if .venv/bin/python bench-test/eigen/eval.py 2>&1 | tee /dev/stderr | grep -q "Overall: ALL PASSED"; then
  echo "SCORE: 1 ($MODEL)"
else
  echo "SCORE: 0 ($MODEL)"
fi
