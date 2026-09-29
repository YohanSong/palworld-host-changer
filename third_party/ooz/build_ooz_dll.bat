@echo off
rem ---------------------------------------------------------------------------
rem Build ooz.dll (Oodle Kraken decompressor) for Palworld Host Changer.
rem
rem Source: https://github.com/powzix/ooz  commit 05038060aa68f9187ae9923b2388ca8db40e58d1
rem         (files in this folder are unmodified copies; GPL-3.0-or-later)
rem Output: ooz.dll (x64), exports only  int Kraken_Decompress(src, src_len, dst, dst_len)
rem
rem Requires Visual Studio with "Desktop development with C++". Run from a normal
rem cmd; the script loads the VS x64 environment itself if cl.exe is not on PATH.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where cl >nul 2>nul && goto build
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDIR=%%i"
if not defined VSDIR goto novs
call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul

:build
if not exist build mkdir build
rem Upstream main() needs <sys/stat.h>; force-include it instead of editing the source.
rem The C++ symbol is exported under its plain name so ctypes can load it.
cl /nologo /O2 /MT /LD /EHsc /DNDEBUG /FIsys/types.h /FIsys/stat.h kraken.cpp lzna.cpp bitknit.cpp stdafx.cpp /Fe:ooz.dll /Fo:build\ /link /EXPORT:Kraken_Decompress=?Kraken_Decompress@@YAHPEBE_KPEAE1@Z
if errorlevel 1 exit /b 1
echo.
echo Built: %CD%\ooz.dll
echo Copy it next to src\host_changer.py (scripts\build_exe.bat does this).
exit /b 0

:novs
echo [error] Visual Studio C++ build tools not found.
exit /b 1
