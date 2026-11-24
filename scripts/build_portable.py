"""Build the portable release: official (PSF-signed) Python runtime + app sources + .bat launcher.

Why not a PyInstaller exe: every PyInstaller variant we tried (onefile/onedir, stock or
self-compiled bootloader) is flagged by Microsoft Defender's cloud ML as
Trojan:Win32/Wacatac!ml. This layout ships only signed Python binaries, plain .py
sources and ooz.dll, so it avoids that false positive.

Run with the official Windows CPython 3.14 x64 whose runtime should be bundled:
    python scripts\\build_portable.py
Output: release\\PalworldHostChanger_v<version>.zip
"""
import os
import py_compile
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from host_changer import __version__  # noqa: E402

PY = sys.base_prefix
VER = f"{sys.version_info.major}{sys.version_info.minor}"
NAME = "PalworldHostChanger"
OUT_DIR = os.path.join(ROOT, "dist_portable", NAME)
ZIP_PATH = os.path.join(ROOT, "release", f"{NAME}_v{__version__}.zip")

RUNTIME_FILES = ["python.exe", "pythonw.exe", "python3.dll", f"python{VER}.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll"]
# DLLs\ entries left out: TLS/sqlite/debug/Windows-only extras the app never imports
SKIP_DLLS = {"_ssl.pyd", "libssl-3.dll", "libcrypto-3.dll", "_sqlite3.pyd", "sqlite3.dll",
             "_remote_debugging.pyd", "_wmi.pyd", "winsound.pyd", "python.cat"}
SKIP_LIB_DIRS = {"test", "tests", "idlelib", "turtledemo", "ensurepip", "venv", "site-packages",
                 "pydoc_data", "__pycache__", "__phello__", "sqlite3"}
TCL_DIRS = ["tcl8.6", "tk8.6", "tcl8"]


def fresh_dir(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)


def build_stdlib_zip(dst_zip):
    """Lib\\ -> legacy-layout .pyc files in one zip (like the official embeddable package).
    dfile is the relative path, so no build-machine path ends up in tracebacks."""
    lib = os.path.join(PY, "Lib")
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, dns, fns in os.walk(lib):
                dns[:] = [d for d in dns if d not in SKIP_LIB_DIRS]
                for fn in fns:
                    if not fn.endswith(".py"):
                        continue
                    src = os.path.join(dp, fn)
                    rel = os.path.relpath(src, lib).replace(os.sep, "/")
                    pyc = os.path.join(tmp, "x.pyc")
                    try:
                        py_compile.compile(src, cfile=pyc, dfile=rel, doraise=True, optimize=0)
                    except py_compile.PyCompileError:
                        continue  # a few stdlib files only compile on other platforms
                    z.write(pyc, rel[:-3] + ".pyc")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if sys.platform != "win32" or sys.maxsize < 2**32:
        sys.exit("Build with 64-bit Windows CPython.")
    fresh_dir(OUT_DIR)
    rt = os.path.join(OUT_DIR, "runtime")
    app = os.path.join(OUT_DIR, "app")
    os.makedirs(rt)
    os.makedirs(app)

    for f in RUNTIME_FILES:
        shutil.copy2(os.path.join(PY, f), rt)
    for f in os.listdir(os.path.join(PY, "DLLs")):
        if f not in SKIP_DLLS and f.lower().endswith((".pyd", ".dll")):
            shutil.copy2(os.path.join(PY, "DLLs", f), rt)
    shutil.copy2(os.path.join(PY, "LICENSE.txt"), os.path.join(rt, "LICENSE_Python.txt"))
    for d in TCL_DIRS:
        shutil.copytree(os.path.join(PY, "tcl", d), os.path.join(rt, "tcl", d))
    build_stdlib_zip(os.path.join(rt, f"python{VER}.zip"))
    # ._pth => isolated: only these paths, no site-packages, env vars ignored
    with open(os.path.join(rt, f"python{VER}._pth"), "w", encoding="ascii", newline="\r\n") as fh:
        fh.write(f"python{VER}.zip\n.\n..\\app\n")

    for f in ("host_changer.py", "host_changer_gui.pyw", "lang.py", "ooz.dll"):
        shutil.copy2(os.path.join(ROOT, "src", f), app)
    import palworld_save_tools
    pst = os.path.dirname(palworld_save_tools.__file__)
    shutil.copytree(pst, os.path.join(app, "palworld_save_tools"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    with open(os.path.join(OUT_DIR, f"{NAME}.bat"), "w", encoding="ascii", newline="\r\n") as fh:
        fh.write('@echo off\n'
                 'rem Palworld Host Changer - starts the GUI with the bundled Python runtime\n'
                 'start "" "%~dp0runtime\\pythonw.exe" "%~dp0app\\host_changer_gui.pyw"\n')

    def text(src, dst):
        s = open(src, encoding="utf-8").read().replace("\r\n", "\n").replace("\n", "\r\n")
        with open(dst, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(s)
    text(os.path.join(ROOT, "docs", "README.txt"), os.path.join(OUT_DIR, "README.txt"))
    text(os.path.join(ROOT, "LICENSE"), os.path.join(OUT_DIR, "LICENSE.txt"))
    text(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), os.path.join(OUT_DIR, "THIRD_PARTY_NOTICES.txt"))

    os.makedirs(os.path.dirname(ZIP_PATH), exist_ok=True)
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dp, _, fns in os.walk(OUT_DIR):
            for fn in fns:
                full = os.path.join(dp, fn)
                z.write(full, os.path.join(NAME, os.path.relpath(full, OUT_DIR)))
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT_DIR) for f in fs)
    print(f"folder {size / 1e6:.1f} MB -> {ZIP_PATH} ({os.path.getsize(ZIP_PATH) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
