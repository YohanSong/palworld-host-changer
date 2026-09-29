@echo off
rem Run the GUI from source (needs Python 3.10+ and: pip install -r requirements.txt)
cd /d "%~dp0..\src"
start "" pythonw host_changer_gui.pyw
