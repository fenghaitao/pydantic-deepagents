"""Evaluation script for eigen.py — tests correctness and speed."""
import time
import numpy as np
from eigen import find_dominant_eigenvalue_and_eigenvector

def reference_solution(A):
    eigenvalues, eigenvectors = np.linalg.eig(A)
    idx = np.argmax(np.abs(eigenvalues))
    return eigenvalues[idx], eigenvectors[:, idx]

def test_correctness(A):
    eigenval, eigenvec = find_dominant_eigenvalue_and_eigenvector(A)
    residual = A @ eigenvec - eigenval * eigenvec
    assert np.allclose(residual, 0, atol=1e-8), f"Failed: residual norm = {np.linalg.norm(residual)}"
    return True

def benchmark(A, n_runs=1000):
    # Warm up
    for _ in range(10):
        find_dominant_eigenvalue_and_eigenvector(A)
    
    times = []
    for _ in range(n_runs):
        start = time.perf_counter()
        find_dominant_eigenvalue_and_eigenvector(A)
        times.append(time.perf_counter() - start)
    
    ref_times = []
    for _ in range(n_runs):
        start = time.perf_counter()
        reference_solution(A)
        ref_times.append(time.perf_counter() - start)
    
    return np.median(times), np.median(ref_times)

if __name__ == "__main__":
    np.random.seed(42)
    sizes = [3, 5, 8, 10]
    all_pass = True
    
    for n in sizes:
        A = np.random.randn(n, n).astype(np.float64)
        try:
            ok = test_correctness(A)
            custom_time, ref_time = benchmark(A)
            speedup = ref_time / custom_time
            status = "PASS" if ok else "FAIL"
            faster = "FASTER" if custom_time < ref_time else "SLOWER"
            print(f"Size {n}x{n}: {status} | custom={custom_time*1e6:.1f}us ref={ref_time*1e6:.1f}us | {speedup:.2f}x ({faster})")
        except Exception as e:
            print(f"Size {n}x{n}: FAIL — {e}")
            all_pass = False
    
    print(f"\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
