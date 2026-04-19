# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_ROOT = Path.cwd()
APP_NAME = "TFT Assistant"


def add_tree(src: Path, dest: str):
    if not src.exists():
        return []
    return [(str(path), f"{dest}/{path.relative_to(src).parent}") for path in src.rglob("*") if path.is_file()]


datas = []
datas += add_tree(PROJECT_ROOT / "assets", "assets")
datas += add_tree(PROJECT_ROOT / "data" / "cache" / "raw", "data/cache/raw")
datas += add_tree(PROJECT_ROOT / "data" / "cache" / "processed", "data/cache/processed")
datas += add_tree(PROJECT_ROOT / "data" / "cache" / "images", "data/cache/images")
datas += collect_data_files("rapidocr")

bundled_model = Path.home() / ".rapidocr_models" / "ch_PP-OCRv4_rec_mobile.onnx"
if bundled_model.exists():
    datas.append((str(bundled_model), "models"))

hiddenimports = [
    "pyautogui",
    "mouseinfo",
    "pyscreeze",
    "pygetwindow",
    "pymsgbox",
    "pytweening",
    "PIL",
    "omegaconf",
    "rapidocr",
    "rapidocr.ch_ppocr_rec",
    "rapidocr.ch_ppocr_rec.main",
    "rapidocr.ch_ppocr_rec.typings",
    "rapidocr.inference_engine",
    "rapidocr.inference_engine.base",
    "rapidocr.inference_engine.onnxruntime",
    "rapidocr.inference_engine.onnxruntime.main",
    "rapidocr.utils.typings",
]
hiddenimports += collect_submodules("rapidocr.inference_engine.onnxruntime")


a = Analysis(
    ["app.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # On Windows, embed a manifest that always requests elevation on launch.
    uac_admin=sys.platform == "win32",
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
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="cc.tftassistant.app",
    )
