@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" goto missing_venv
"%VENV_PYTHON%" scripts\launcher.py %*
exit /b %ERRORLEVEL%
:missing_venv
echo [ERROR] Python virtual environment .venv was not found. See README.md.
exit /b 1
