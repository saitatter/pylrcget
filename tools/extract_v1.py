#!/usr/bin/env python3
"""Extract and summarize V1 (release) implementation."""

import subprocess
from pathlib import Path

# Get release version code
result = subprocess.run(
    ['git', 'show', '90bdd58:src/ui/workers/ai_sync_worker.py'],
    capture_output=True,
    text=True,
    cwd=str(Path.cwd())
)

v1_code = result.stdout

# Find main alignment function
import re

# Extract key methods
pattern_align = r'def _align_lyrics_to_segments.*?(?=\n    def |\nclass |\Z)'
match_align = re.search(pattern_align, v1_code, re.DOTALL)

if match_align:
    align_method = match_align.group(0)
    print("="*100)
    print("RELEASE 1.10.1 - _align_lyrics_to_segments method:")
    print("="*100)
    print(align_method[:2000])
    print("\n[... rest truncated ...]\n")
else:
    # Look for any alignment function
    lines = v1_code.split('\n')
    for i, line in enumerate(lines):
        if '_align' in line or 'segment' in line.lower():
            print(f"{i}: {line}")
