#!/usr/bin/env python3
"""Benchmark: Release 1.10.1 (greedy) vs Current (Viterbi) across all test tracks."""

import json
import sys
from pathlib import Path
import subprocess

test_dir = Path('C:\\Users\\andrvoicu\\Downloads\\music_test')

# Save current state
print("[*] Saving current state...")
subprocess.run(['git', 'stash'], cwd=str(Path.cwd()), capture_output=True, check=False)

try:
    # Checkout release version
    print("[*] Checking out release 1.10.1 (90bdd58)...")
    subprocess.run(['git', 'checkout', '90bdd58'], cwd=str(Path.cwd()), capture_output=True, check=True)
    
    # Run benchmark on release
    print("[*] Running benchmark on RELEASE 1.10.1 (Whisper base + greedy)...")
    result_v1 = subprocess.run(
        [sys.executable, 'tools/benchmark_all_tracks.py'],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=1200
    )
    print(result_v1.stdout[-500:] if len(result_v1.stdout) > 500 else result_v1.stdout)
    
    # Save v1 results
    v1_report = Path('tools') / 'whisperx_test_output' / 'benchmark_all_tracks.json'
    v1_results = {}
    if v1_report.exists():
        v1_results = json.loads(v1_report.read_text())
    
    # Restore current state
    print("\n[*] Restoring current state...")
    subprocess.run(['git', 'checkout', '-'], cwd=str(Path.cwd()), capture_output=True, check=True)
    
    # Run benchmark on current
    print("[*] Running benchmark on CURRENT (Viterbi + multi-strategy)...")
    result_v3 = subprocess.run(
        [sys.executable, 'tools/benchmark_all_tracks.py'],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=1200
    )
    print(result_v3.stdout[-500:] if len(result_v3.stdout) > 500 else result_v3.stdout)
    
    # Get v3 results
    v3_results = {}
    if v1_report.exists():
        v3_results = json.loads(v1_report.read_text())
    
    # Compare
    print("\n" + "="*100)
    print("COMPARISON: Release 1.10.1 (Greedy Whisper) vs Current (Viterbi Multi-Strategy)")
    print("="*100)
    print()
    
    all_tracks = set(v1_results.keys()) | set(v3_results.keys())
    
    for track in sorted(all_tracks):
        v1 = v1_results.get(track, {})
        v3 = v3_results.get(track, {})
        
        if not v1 or not v3:
            print(f"{track}: MISSING DATA")
            continue
        
        v1_fuzzy = v1.get('fuzzy_local', {})
        v3_viterbi = v3.get('viterbi', {})
        
        v1_mean = v1_fuzzy.get('mean_abs_s', 999)
        v3_mean = v3_viterbi.get('mean_abs_s', 999)
        v1_p95 = v1_fuzzy.get('p95_abs_s', 999)
        v3_p95 = v3_viterbi.get('p95_abs_s', 999)
        
        mean_pct = ((v1_mean - v3_mean) / v1_mean * 100) if v1_mean > 0 else 0
        p95_pct = ((v1_p95 - v3_p95) / v1_p95 * 100) if v1_p95 > 0 else 0
        
        print(f"{track}")
        print(f"  MEAN:  Release={v1_mean:6.2f}s  ->  Current={v3_mean:6.2f}s  ({mean_pct:+6.1f}%)")
        print(f"  P95:   Release={v1_p95:6.2f}s  ->  Current={v3_p95:6.2f}s  ({p95_pct:+6.1f}%)")
        print()
    
    # Aggregated stats
    print("="*100)
    print("AGGREGATED METRICS")
    print("="*100)
    all_v1_means = [v1_results[t]['fuzzy_local']['mean_abs_s'] for t in v1_results if v1_results[t]['fuzzy_local']['mean_abs_s']]
    all_v3_means = [v3_results[t]['viterbi']['mean_abs_s'] for t in v3_results if v3_results[t]['viterbi']['mean_abs_s']]
    
    if all_v1_means and all_v3_means:
        import statistics
        v1_mean_avg = statistics.mean(all_v1_means)
        v3_mean_avg = statistics.mean(all_v3_means)
        improvement = ((v1_mean_avg - v3_mean_avg) / v1_mean_avg * 100)
        print(f"Average MEAN across all tracks:")
        print(f"  Release: {v1_mean_avg:.2f}s")
        print(f"  Current: {v3_mean_avg:.2f}s")
        print(f"  Improvement: {improvement:+.1f}%")

finally:
    # Restore if anything went wrong
    print("\n[*] Finalizing...")
    subprocess.run(['git', 'stash', 'pop'], cwd=str(Path.cwd()), capture_output=True, check=False)
