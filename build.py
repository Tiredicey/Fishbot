import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import subprocess
import shutil
import logging
import time
import venv
import platform
import json
from pathlib import Path

BUILD_LOG   = "build.log"
VENV_DIR    = Path(".fishbot_venv")
REQ_FILE    = Path("requirements.txt")
SPEC_FILE   = Path("fishbot.spec")
SOURCE_FILE = Path("fishbot.py")
DIST_DIR    = Path("dist")
OUT_EXE     = DIST_DIR / "FishBot.exe"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BUILD_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("BuildOrchestrator")

TUTORIAL = """
╔══════════════════════════════════════════════════════════════════════════╗
║                    FISHBOT  BUILD  SYSTEM  v1.1                          ║
║                     Beginner-Friendly Guide                               ║
╠══════════════════════════════════════════════════════════════════════════╣
║  What this script does — step by step:                                    ║
║  1. Changes working directory to its own folder  (fixes system32 bug)    ║
║  2. Checks Python version and warns about known compatibility issues      ║
║  3. Creates an isolated virtual environment  (.fishbot_venv/)             ║
║  4. Installs every dependency from requirements.txt into that venv        ║
║  5. Runs PyInstaller with fishbot.spec → dist/FishBot.exe                 ║
║  6. Verifies the .exe exists and reports its size                         ║
║                                                                           ║
║  Full log always written to: build.log                                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

STEP_WIDTH = 60


def banner(msg: str):
    bar = "─" * STEP_WIDTH
    log.info(f"\n{bar}\n  {msg}\n{bar}")


def abort(msg: str, hint: str = ""):
    log.error(f"\n{'!'*STEP_WIDTH}")
    log.error(f"  BUILD STOPPED: {msg}")
    if hint:
        log.error(f"  HINT: {hint}")
    log.error(f"{'!'*STEP_WIDTH}")
    sys.exit(1)


def run(cmd: list, env=None, cwd=None) -> subprocess.CompletedProcess:
    log.debug(f"RUN: {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log.debug(f"  stdout: {line}")
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log.debug(f"  stderr: {line}")
    return result


def check_python():
    banner("Step 1/5 — Python version check")
    v = sys.version_info
    log.info(f"Working directory: {os.getcwd()}")
    log.info(f"Python {v.major}.{v.minor}.{v.micro} on {platform.system()}")
    log.info(f"Executable: {sys.executable}")

    if platform.system() != "Windows":
        abort(
            "FishBot only runs on Windows.",
            "Requires win32api, mss Windows backend, pydirectinput.",
        )
    if v < (3, 9):
        abort(
            f"Python 3.9+ required, found {v.major}.{v.minor}.",
            "Download Python 3.11 from https://python.org/downloads",
        )
    if v >= (3, 13):
        log.warning(
            f"Python {v.major}.{v.minor} detected. "
            "Recommended: 3.11 or 3.12 for maximum wheel availability. "
            "Attempting anyway — if pip fails on any package, install "
            "Python 3.11 side-by-side and re-run."
        )
    else:
        log.info("Python version ideal (3.9–3.12)")


def check_source():
    banner("Step 1b — Source file check")
    log.info(f"Looking for files in: {os.getcwd()}")
    missing = []
    for f in [SOURCE_FILE, SPEC_FILE, REQ_FILE]:
        if f.exists():
            log.info(f"  FOUND: {f}")
        else:
            log.error(f"  MISSING: {f}")
            missing.append(str(f))
    if missing:
        abort(
            f"Missing files: {', '.join(missing)}",
            "All 4 files must be in the same directory:\n"
            "  fishbot.py  fishbot.spec  requirements.txt  build.py",
        )
    log.info("All required files present")


def make_venv():
    banner("Step 2/5 — Virtual environment")
    if VENV_DIR.exists():
        log.info(f"Reusing existing venv at {VENV_DIR.resolve()}")
    else:
        log.info(f"Creating venv at {VENV_DIR.resolve()} ...")
        try:
            venv.create(str(VENV_DIR), with_pip=True, clear=False)
        except Exception as e:
            abort(
                f"venv creation failed: {e}",
                "Try: delete .fishbot_venv\\ and re-run as Administrator.",
            )
        log.info("venv created")
    return _venv_python()


def _venv_python() -> Path:
    py = VENV_DIR / "Scripts" / "python.exe"
    if not py.exists():
        abort(
            f"venv python.exe not found at {py}",
            "Delete .fishbot_venv\\ and re-run.",
        )
    log.info(f"venv python: {py.resolve()}")
    return py


def install_deps(venv_py: Path):
    banner("Step 3/5 — Installing dependencies")
    log.info("Upgrading pip ...")
    r = run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    if r.returncode != 0:
        log.warning("pip upgrade non-zero — continuing")

    log.info(f"Installing from {REQ_FILE} ...")
    r = run([
        str(venv_py), "-m", "pip", "install",
        "-r", str(REQ_FILE),
        "--quiet",
        "--no-warn-script-location",
    ])
    if r.returncode != 0:
        log.error("pip install failed — attempting individual installs for diagnosis")
        _install_individual(venv_py)
        return

    _verify_imports(venv_py)
    log.info("All dependencies installed")


def _install_individual(venv_py: Path):
    packages = [
        "mss",
        "pydirectinput",
        "opencv-python",
        "numpy",
        "keyboard",
        "pywin32",
        "psutil",
        "Pillow",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
    ]
    failed = []
    for pkg in packages:
        r = run([str(venv_py), "-m", "pip", "install", pkg, "--quiet"])
        if r.returncode != 0:
            log.error(f"  FAILED: {pkg}")
            failed.append(pkg)
        else:
            log.info(f"  OK: {pkg}")
    if failed:
        abort(
            f"Could not install: {', '.join(failed)}",
            "These packages may not yet have wheels for your Python version.\n"
            "Install Python 3.11 from python.org and re-run.",
        )
    _verify_imports(venv_py)


def _verify_imports(venv_py: Path):
    probes = [
        "mss", "pydirectinput", "cv2", "numpy",
        "keyboard", "win32gui", "psutil", "PIL", "PyInstaller",
    ]
    log.info("Verifying critical imports ...")
    failed = []
    for mod in probes:
        r = run([str(venv_py), "-c", f"import {mod}; print('ok')"])
        if r.returncode != 0 or "ok" not in r.stdout:
            failed.append(mod)
            log.error(f"  MISSING: {mod}\n    {r.stderr.strip()[:200]}")
        else:
            log.debug(f"  OK: {mod}")
    if failed:
        abort(
            f"Import check failed for: {', '.join(failed)}",
            "Run manually:\n"
            f"  {venv_py} -m pip install " + " ".join(failed),
        )
    log.info("Import verification passed")


def run_pyinstaller(venv_py: Path):
    banner("Step 4/5 — PyInstaller build")
    for d in [Path("build"), DIST_DIR]:
        if d.exists():
            log.info(f"Cleaning {d}/ ...")
            shutil.rmtree(d, ignore_errors=True)

    log.info("Running PyInstaller (60–120 seconds) ...")
    t0 = time.time()
    r = run([
        str(venv_py), "-m", "PyInstaller",
        str(SPEC_FILE),
        "--clean",
        "--noconfirm",
        "--log-level", "WARN",
    ])
    elapsed = time.time() - t0

    if r.returncode != 0:
        abort(
            f"PyInstaller exited {r.returncode} after {elapsed:.0f}s.",
            "Search build.log for 'ERROR' to find the exact cause.",
        )
    log.info(f"PyInstaller finished in {elapsed:.1f}s")


def verify_output():
    banner("Step 5/5 — Verifying output")
    if not OUT_EXE.exists():
        abort(
            f"Expected exe not found: {OUT_EXE}",
            "Check build.log for PyInstaller errors.",
        )
    size_mb = OUT_EXE.stat().st_size / 1_048_576
    log.info(f"SUCCESS:  {OUT_EXE.resolve()}")
    log.info(f"Size:     {size_mb:.1f} MB")
    _write_manifest(size_mb)


def _write_manifest(size_mb: float):
    manifest = {
        "built_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python":    f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform":  platform.system(),
        "output":    str(OUT_EXE.resolve()),
        "size_mb":   round(size_mb, 2),
    }
    try:
        with open(DIST_DIR / "build_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        log.warning(f"Manifest write: {e}")


def print_summary():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║               BUILD COMPLETE  ✓                         ║")
    print("║  Output:  dist/FishBot.exe                              ║")
    print("║                                                          ║")
    print("║  FIRST RUN TIPS:                                         ║")
    print("║  • Right-click FishBot.exe → Run as Administrator        ║")
    print("║  • Open Roblox first, then start FishBot                 ║")
    print("║  • Ctrl+Shift+S  =  start / stop                        ║")
    print("║  • Calibrate Bobber → Splash → draw Scan Region first   ║")
    print("║  • bot.log and debug_*.png appear next to the exe       ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()


def main():
    print(TUTORIAL)
    check_python()
    check_source()
    venv_py = make_venv()
    install_deps(venv_py)
    run_pyinstaller(venv_py)
    verify_output()
    print_summary()


if __name__ == "__main__":
    main()