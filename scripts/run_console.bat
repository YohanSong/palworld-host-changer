@echo off
rem Console version: drag a world folder (the one with Level.sav) onto this file.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\src"
python host_changer.py "%~1"
pause
