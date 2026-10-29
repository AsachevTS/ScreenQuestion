@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Сначала запустите install.bat.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import tkinter, mss, PIL, pystray, requests" >nul 2>nul
if errorlevel 1 (
    echo Не все библиотеки установлены. Запустите install.bat повторно.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0screen_question.py"
