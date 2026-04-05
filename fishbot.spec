import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_all

block_cipher = None

mss_datas,     mss_bins,     mss_hiddens     = collect_all("mss")
cv2_datas,     cv2_bins,     cv2_hiddens     = collect_all("cv2")
pil_datas,     pil_bins,     pil_hiddens     = collect_all("PIL")
psutil_datas,  psutil_bins,  psutil_hiddens  = collect_all("psutil")

all_datas    = mss_datas   + cv2_datas   + pil_datas   + psutil_datas
all_bins     = mss_bins    + cv2_bins    + pil_bins    + psutil_bins
all_hiddens  = (
    mss_hiddens + cv2_hiddens + pil_hiddens + psutil_hiddens
    + [
        "win32gui", "win32process", "win32api", "win32con",
        "win32security", "win32service", "win32event",
        "pywintypes", "winerror",
        "pythoncom",
        "win32ctypes.pywin32", "win32ctypes.pywin32.pywintypes",
        "keyboard._winkeyboard",
        "pydirectinput",
        "mss.windows", "mss.base", "mss.screenshot",
        "PIL.Image", "PIL.ImageTk", "PIL.ImageOps",
        "cv2", "numpy", "numpy.core._methods", "numpy.lib.format",
        "tkinter", "tkinter.ttk", "tkinter.messagebox",
        "psutil._pswindows",
        "pkg_resources.py2_warn",
        "json", "logging", "threading", "dataclasses", "enum", "typing",
    ]
)

a = Analysis(
    ["fishbot.py"],
    pathex=[os.path.abspath(".")],
    binaries=all_bins,
    datas=all_datas,
    hiddenimports=all_hiddens,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "PyQt5", "PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="FishBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll", "python*.dll"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
    uac_admin=True,
)