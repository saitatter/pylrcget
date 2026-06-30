#!/usr/bin/env python3
"""Extract release v1 alignment logic and create detailed comparison report."""

import subprocess
import json
from pathlib import Path

# Get release version code
result = subprocess.run(
    ['git', 'show', '90bdd58:src/ui/workers/ai_sync_worker.py'],
    capture_output=True,
    text=True,
    cwd=str(Path.cwd())
)

v1_code = result.stdout

# Extract key function
def extract_function(code, func_name):
    lines = code.split('\n')
    start = None
    for i, line in enumerate(lines):
        if f'def {func_name}' in line:
            start = i
            break
    if start is None:
        return None
    
    # Find end of function (next def at same indentation)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith(' '):
            end = i
            break
        if lines[i].startswith(' ' * indent + 'def '):
            end = i
            break
    if end is None:
        end = len(lines)
    
    return '\n'.join(lines[start:end])

# Extract the main alignment function
align_func = extract_function(v1_code, '_align_lyrics_to_segments')

print("="*100)
print("RELEASE 1.10.1 - ALIGNMENT FUNCTION (from commit 90bdd58)")
print("="*100)
if align_func:
    lines = align_func.split('\n')[:80]  # First 80 lines
    for i, line in enumerate(lines, 1):
        print(f"{i:3d}: {line}")
    print(f"\n... [function continues, total {len(align_func.split(chr(10)))} lines] ...\n")
else:
    print("Could not extract function")

# List all functions in v1
print("\n" + "="*100)
print("ALL FUNCTIONS IN RELEASE 1.10.1")
print("="*100)
lines = v1_code.split('\n')
for i, line in enumerate(lines):
    if line.strip().startswith('def '):
        print(f"Line {i+1}: {line.strip()[:80]}")

# Now show current v3
print("\n" + "="*100)
print("CURRENT (v3) - KEY STATISTICS")
print("="*100)

v3_results = Path('tools/whisperx_test_output/benchmark_all_tracks.json').read_text()
v3_data = json.loads(v3_results)

print("\nMetrics comparison (V3 Fuzzy vs V3 Viterbi):")
print(f"{'Track':<30} {'Fuzzy Mean':<15} {'Viterbi Mean':<15} {'Improvement':<15}")
print("-" * 75)

total_fuzzy_mean = 0
total_viterbi_mean = 0
count = 0

for track, metrics in v3_data.items():
    fuzzy_mean = metrics['fuzzy_local']['mean_abs_s']
    viterbi_mean = metrics['viterbi']['mean_abs_s']
    improvement = ((fuzzy_mean - viterbi_mean) / fuzzy_mean * 100) if fuzzy_mean > 0 else 0
    
    print(f"{track:<30} {fuzzy_mean:>12.2f}s {viterbi_mean:>14.2f}s {improvement:>13.1f}%")
    
    total_fuzzy_mean += fuzzy_mean
    total_viterbi_mean += viterbi_mean
    count += 1

print("-" * 75)
avg_fuzzy = total_fuzzy_mean / count if count > 0 else 0
avg_viterbi = total_viterbi_mean / count if count > 0 else 0
avg_improvement = ((avg_fuzzy - avg_viterbi) / avg_fuzzy * 100) if avg_fuzzy > 0 else 0

print(f"{'AVERAGE':<30} {avg_fuzzy:>12.2f}s {avg_viterbi:>14.2f}s {avg_improvement:>13.1f}%")
