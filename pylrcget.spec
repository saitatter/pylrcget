from pathlib import Path
import sys


SPEC_PATH = Path(globals().get("__file__", "pylrcget.spec")).resolve()
ROOT = SPEC_PATH.parent if SPEC_PATH.exists() else Path.cwd()

if not (3, 10) <= tuple(sys.version_info[:2]) <= (3, 13):
    raise SystemExit(
        "PyLrcGet builds require Python 3.10-3.13; "
        f"the current interpreter is Python {sys.version_info[0]}.{sys.version_info[1]}."
    )

AI_RUNTIME_DATAS = [
    (str(path), "ai_runtime_src/ui/workers")
    for path in (ROOT / "src" / "ui" / "workers").glob("*.py")
]

AI_EXCLUDES = [
    "torch",
    "torchaudio",
    "torchcodec",
    "whisperx",
    "faster_whisper",
    "ctranslate2",
    "soundfile",
    "pyannote",
    "transformers",
    "demucs",
    "pandas",
    "scipy",
    "onnxruntime",
    "librosa",
    "g2p_en",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT), str(ROOT / "src")],
    datas=[
        *AI_RUNTIME_DATAS,
        (str(ROOT / "src" / "ui" / "qss"), "ui/qss"),
        (str(ROOT / "src" / "ui" / "assets"), "ui/assets"),
        (str(ROOT / "pyproject.toml"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=AI_EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pylrcget",
    icon=str(ROOT / "src" / "ui" / "assets" / "app-icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="pylrcget",
)
