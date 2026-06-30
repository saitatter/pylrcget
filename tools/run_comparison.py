#!/usr/bin/env python3
"""Benchmark: Release 1.10.1 vs Current (Auto+Viterbi) - clean comparison."""

import json
import sys
from pathlib import Path
import subprocess

test_dir = Path('C:\\Users\\andrvoicu\\Downloads\\music_test')
results_file = Path('tools/whisperx_test_output/benchmark_comparison.json')
results_file.parent.mkdir(parents=True, exist_ok=True)

def run_benchmark_on_version(version_name, git_ref=None):
    """Run benchmark on a specific git version."""
    
    if git_ref:
        print(f"\n[*] Checking out {version_name} ({git_ref})...")
        subprocess.run(['git', 'checkout', git_ref], 
                      cwd=str(Path.cwd()), capture_output=True, check=True)
    
    print(f"[*] Running benchmark on {version_name}...")
    result = subprocess.run(
        [sys.executable, 'tools/benchmark_v_single.py'],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=1200,
        env={**dict(subprocess.os.environ), 'PYTHONPATH': 'src'}
    )
    
    print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
    
    if result.returncode != 0:
        print(f"ERROR: {result.stderr[-500:]}")
        return None
    
    # Load results
    bench_file = Path('tools/whisperx_test_output/benchmark_all_tracks.json')
    if bench_file.exists():
        return json.loads(bench_file.read_text())
    return None

# Save current state
print("[*] Saving current state...")
subprocess.run(['git', 'stash'], cwd=str(Path.cwd()), capture_output=True)

try:
    # V1: Release 1.10.1
    v1_results = run_benchmark_on_version("Release 1.10.1", "90bdd58")
    
    # Restore current
    print("\n[*] Restoring to HEAD (current)...")
    subprocess.run(['git', 'checkout', '-'], cwd=str(Path.cwd()), capture_output=True, check=True)
    
    # V3: Current (with auto+viterbi)
    v3_results = run_benchmark_on_version("Current (Auto+Viterbi)", None)
    
    # Compare
    if v1_results and v3_results:
        print("\n" + "="*120)
        print("DETAILED COMPARISON: Release 1.10.1 vs Current (Auto+Viterbi)")
        print("="*120)
        
        comparison = {}
        
        for track in sorted(set(v1_results.keys()) | set(v3_results.keys())):
            v1 = v1_results.get(track, {})
            v3 = v3_results.get(track, {})
            
            if not v1 or not v3:
                print(f"\n{track}: MISSING DATA")
                continue
            
            # Get first strategy from each (fuzzy_local is what they both report)
            v1_fuzzy = v1.get('fuzzy_local', {})
            v3_best = v3.get('auto_viterbi', v3.get('viterbi', v3.get('fuzzy_local', {})))
            
            if not v1_fuzzy or not v3_best:
                continue
            
            v1_mean = v1_fuzzy.get('mean_abs_s')
            v3_mean = v3_best.get('mean_abs_s')
            v1_median = v1_fuzzy.get('median_abs_s')
            v3_median = v3_best.get('median_abs_s')
            v1_p95 = v1_fuzzy.get('p95_abs_s')
            v3_p95 = v3_best.get('p95_abs_s')
            
            if v1_mean and v3_mean:
                mean_gain = ((v1_mean - v3_mean) / v1_mean * 100)
                median_gain = ((v1_median - v3_median) / v1_median * 100) if v1_median and v3_median else None
                p95_gain = ((v1_p95 - v3_p95) / v1_p95 * 100) if v1_p95 and v3_p95 else None
                
                comparison[track] = {
                    'v1_mean': v1_mean,
                    'v3_mean': v3_mean,
                    'mean_gain': mean_gain,
                    'v1_median': v1_median,
                    'v3_median': v3_median,
                    'median_gain': median_gain,
                    'v1_p95': v1_p95,
                    'v3_p95': v3_p95,
                    'p95_gain': p95_gain,
                }
                
                print(f"\n{track}")
                print(f"  MEAN:   {v1_mean:7.2f}s -> {v3_mean:7.2f}s  ({mean_gain:+7.1f}%)")
                if median_gain:
                    print(f"  MEDIAN: {v1_median:7.2f}s -> {v3_median:7.2f}s  ({median_gain:+7.1f}%)")
                if p95_gain:
                    print(f"  P95:    {v1_p95:7.2f}s -> {v3_p95:7.2f}s  ({p95_gain:+7.1f}%)")
        
        # Aggregated
        print("\n" + "="*120)
        print("AGGREGATED RESULTS")
        print("="*120)
        
        all_mean_v1 = [c['v1_mean'] for c in comparison.values()]
        all_mean_v3 = [c['v3_mean'] for c in comparison.values()]
        all_median_v1 = [c['v1_median'] for c in comparison.values()]
        all_median_v3 = [c['v3_median'] for c in comparison.values()]
        
        import statistics
        
        print(f"\nAverage MEAN error across all tracks:")
        print(f"  Release 1.10.1:  {statistics.mean(all_mean_v1):.2f}s")
        print(f"  Current (V3):    {statistics.mean(all_mean_v3):.2f}s")
        print(f"  Improvement:     {((statistics.mean(all_mean_v1) - statistics.mean(all_mean_v3)) / statistics.mean(all_mean_v1) * 100):+.1f}%")
        
        print(f"\nAverage MEDIAN error across all tracks:")
        print(f"  Release 1.10.1:  {statistics.mean(all_median_v1):.2f}s")
        print(f"  Current (V3):    {statistics.mean(all_median_v3):.2f}s")
        print(f"  Improvement:     {((statistics.mean(all_median_v1) - statistics.mean(all_median_v3)) / statistics.mean(all_median_v1) * 100):+.1f}%")
        
        # Save results
        results_file.write_text(json.dumps(comparison, indent=2))
        print(f"\nResults saved to {results_file}")

finally:
    print("\n[*] Restoring working tree...")
    subprocess.run(['git', 'stash', 'pop'], cwd=str(Path.cwd()), capture_output=True)
