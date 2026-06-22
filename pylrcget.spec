from pathlib import Path
from importlib import import_module
from PyInstaller.utils.hooks import collect_data_files


SPEC_PATH = Path(globals().get("__file__", "pylrcget.spec")).resolve()
ROOT = SPEC_PATH.parent if SPEC_PATH.exists() else Path.cwd()

def _optional_collect_data_files(package: str):
    try:
        return collect_data_files(package)
    except Exception:
        return []

AI_DATAS = _optional_collect_data_files("whisper") + _optional_collect_data_files("demucs")

def _optional_package_subdir(package: str, subdir: str):
    try:
        mod = import_module(package)
        base = Path(mod.__file__).resolve().parent
        path = base / subdir
        if path.is_dir():
            return [(str(path), f"{package}/{subdir}")]
    except Exception:
        return []
    return []

AI_DATAS += _optional_package_subdir("whisper", "assets")


a = Analysis(
    ["main.py"],
    pathex=[str(ROOT), str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "src" / "ui" / "qss"), "ui/qss"),
        (str(ROOT / "src" / "ui" / "assets"), "ui/assets"),
        (str(ROOT / "pyproject.toml"), "."),
    ] + AI_DATAS,
    hiddenimports=[],
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
