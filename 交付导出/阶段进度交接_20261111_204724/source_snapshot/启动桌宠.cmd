@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0dist\Momo\Momo.exe" (
    start "" "%~dp0dist\Momo\Momo.exe"
    exit /b
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b
)
echo Please install Python, create .venv and install requirements.txt first.
echo See README.md for setup instructions.
pause

