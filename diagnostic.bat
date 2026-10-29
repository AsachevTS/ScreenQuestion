@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Сначала запустите install.bat.
    pause
    exit /b 1
)
echo === Тесты ===
".venv\Scripts\python.exe" -m unittest -v
echo.
echo === Запуск с консолью (ошибки будут видны здесь) ===
".venv\Scripts\python.exe" screen_question.py
pause
