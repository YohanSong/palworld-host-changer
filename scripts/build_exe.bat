@echo off
rem Build dist\PalworldHostChanger.exe (single file, no Python needed on the target PC).
rem Prerequisite: src\ooz.dll  (prebuilt in the repo, or run third_party\ooz\build_ooz_dll.bat)
setlocal
cd /d "%~dp0.."
if not exist src\ooz.dll (
    echo [error] src\ooz.dll missing. Run third_party\ooz\build_ooz_dll.bat and copy ooz.dll to src\
    exit /b 1
)
python -m pip install -r requirements-build.txt || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name PalworldHostChanger ^
    --version-file "%CD%\scripts\version_info.txt" ^
    --add-binary "%CD%\src\ooz.dll;." ^
    --distpath dist --workpath build --specpath build ^
    src\host_changer_gui.pyw || exit /b 1
echo.
echo Built: %CD%\dist\PalworldHostChanger.exe
endlocal
