from pathlib import Path
from importlib import import_module
from PyInstaller.utils.hooks import collect_all, collect_data_files


SPEC_PATH = Path(globals().get("__file__", "pylrcget.spec")).resolve()
ROOT = SPEC_PATH.parent if SPEC_PATH.exists() else Path.cwd()

def _optional_collect_data_files(package: str):
    try:
        return collect_data_files(package)
    except Exception:
        return []

AI_DATAS = []
AI_BINARIES = []
AI_HIDDENIMPORTS = [
    "whisperx",
    "whisperx.asr",
    "whisperx.alignment",
    "whisperx.audio",
    "whisperx.diarize",
    "whisperx.types",
    "whisperx.utils",
    "whisperx.vad",
    "soundfile",
    "_soundfile",
    "_soundfile_data",
    "cffi",
    "_cffi_backend",
]

def _collect_ai_package(package: str):
    global AI_DATAS, AI_BINARIES, AI_HIDDENIMPORTS
    try:
        datas, binaries, hiddenimports = collect_all(package)
        AI_DATAS.extend(datas)
        AI_BINARIES.extend(binaries)
        AI_HIDDENIMPORTS.extend(hiddenimports)
    except Exception as exc:
        print(f"Warning: could not collect AI package {package}: {exc}")


for pkg in ["whisperx", "faster_whisper", "ctranslate2", "soundfile", "torchaudio", "torch"]:
    _collect_ai_package(pkg)


a = Analysis(
    ["main.py"],
    pathex=[str(ROOT), str(ROOT / "src")],
    binaries=AI_BINARIES,
    datas=[
        (str(ROOT / "src" / "ui" / "qss"), "ui/qss"),
        (str(ROOT / "src" / "ui" / "assets"), "ui/assets"),
        (str(ROOT / "pyproject.toml"), "."),
    ] + AI_DATAS,
    hiddenimports=AI_HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
