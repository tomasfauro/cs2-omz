@echo off
REM Build script for CS2 OMZ
echo [CS2 OMZ] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

echo [CS2 OMZ] Building executable with PyInstaller...
pyinstaller --onefile --windowed --uac-admin --icon=assets/logo.ico --name=CS2OMZ main.py
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo [CS2 OMZ] Build complete. Output: dist\CS2OMZ.exe
pause
