@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo Установка программы «Вопрос с экрана»...
if exist ".venv\Scripts\python.exe" goto packages
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; assert sys.version_info >= (3, 10)"
    if errorlevel 1 goto no_python
    py -3 -m venv .venv
) else (
    where python >nul 2>nul
    if errorlevel 1 goto no_python
    python -c "import sys; assert sys.version_info >= (3, 10)"
    if errorlevel 1 goto no_python
    python -m venv .venv
)
if errorlevel 1 goto failed
:packages
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import tkinter, mss, PIL, pystray, requests, keyring; print('Библиотеки доступны.')"
if errorlevel 1 goto failed
echo.
echo Готово. Запустите start.bat.
pause
exit /b 0
:no_python
echo.
echo Установите Python 3.10 или новее с python.org (с tcl/tk) и повторите запуск.
pause
exit /b 1
:failed
echo.
echo Установка не завершена. Проверьте сообщение выше и соединение с интернетом.
pause
exit /b 1
