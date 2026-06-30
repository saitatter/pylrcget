#!/usr/bin/env python3
"""Analyze repeat structure in test tracks."""

from pathlib import Path

def extract_plain_from_lrc(path: str):
    lines = []
    for ln in Path(path).read_text(encoding='utf-8', errors='ignore').splitlines():
        ln = ln.strip()
        if not ln or not ln.startswith('['):
            continue
        try:
            ts_end = ln.index(']')
            text = ln[ts_end+1:].strip()
            if text:
                lines.append(text)
        except:
            pass
    return lines

test_dir = Path('C:\\Users\\andrvoicu\\Downloads\\music_test')

for flac_file in sorted(test_dir.glob('*.flac')):
    stem = flac_file.stem
    lrc_file = test_dir / f'{stem}.lrc'
    
    if not lrc_file.exists():
        continue
    
    plain_lines = extract_plain_from_lrc(str(lrc_file))
    
    # Count repeats
    norms = [l.strip().lower() for l in plain_lines]
    unique = set(norms)
    repeat_count = {n: norms.count(n) for n in unique if norms.count(n) > 1}
    
    total_repeated_lines = sum(1 for n in norms if norms.count(n) > 1)
    pct_repeated = total_repeated_lines / len(norms) * 100 if norms else 0
    
    print(f"{stem}")
    print(f"  Total lines: {len(plain_lines)}")
    print(f"  Unique: {len(unique)}")
    print(f"  Repeated lines: {total_repeated_lines} ({pct_repeated:.1f}%)")
    print(f"  Most common repeats: {sorted(repeat_count.items(), key=lambda x: -x[1])[:3]}")
    print()
