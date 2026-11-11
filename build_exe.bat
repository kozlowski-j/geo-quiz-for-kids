@echo off
rem Builds dist\WorldExplorer.exe (single file, no console window).
rem Run from the project folder with the virtual environment active
rem and requirements-dev.txt installed.
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WorldExplorer --add-data "data;data" main.py
