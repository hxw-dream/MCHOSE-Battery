@echo off
setlocal
set PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe
if not exist "%PYW%" for /f "delims=" %%i in ('where pythonw 2^>nul') do set PYW=%%i
if not exist "%PYW%" (
  echo pythonw.exe not found. Install Python 3.12 first.
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0tray_app.py"
