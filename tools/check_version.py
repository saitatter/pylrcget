#!/usr/bin/env python3
"""Debug Nancy track: see which strategy auto-selector picks and why median degrades."""

import sys
from pathlib import Path
import importlib.util

worker_path = Path('src') / 'ui' / 'workers' / 'ai_sync_worker.py'
spec = importlib.util.spec_from_file_location('ai_sync_worker', str(worker_path))
ai_module = importlib.util.module_from_spec(spec)

import types
if 'PySide6' not in sys.modules:
    pyside = types.ModuleType('PySide6')
    qtcore = types.ModuleType('PySide6.QtCore')
    class _QThread:
        pass
    def _Signal(*args, **kwargs):
        return None
    qtcore.QThread = _QThread
    qtcore.Signal = _Signal
    pyside.QtCore = qtcore
    sys.modules['PySide6'] = pyside
    sys.modules['PySide6.QtCore'] = qtcore

spec.loader.exec_module(ai_module)

# Check what functions exist
print("Functions in ai_sync_worker:")
for name in dir(ai_module):
    if 'align' in name.lower() or 'select' in name.lower():
        print(f"  - {name}")

# Check if current version has Viterbi
import inspect
_align = getattr(ai_module, '_align_lyrics_to_segments', None)
if _align:
    sig = inspect.signature(_align)
    print(f"\n_align_lyrics_to_segments parameters: {list(sig.parameters.keys())}")
    
    # Check if viterbi is there
    if 'enable_viterbi' in sig.parameters:
        print("✓ Current version HAS Viterbi support")
    else:
        print("✗ Current version NO Viterbi support (back to v1)")
