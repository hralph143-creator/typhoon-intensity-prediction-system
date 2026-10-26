@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 云浪智析 - 启动器
cd /d "%~dp0"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" goto missing_venv

if /i "%~1"=="--no-browser" goto launch_no_browser
"%VENV_PYTHON%" scripts\launcher.py %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
if not "%LAUNCH_EXIT%"=="0" goto launch_failed
if "%~1"=="" start "" "http://127.0.0.1:5173/"
exit /b 0

:launch_no_browser
if not "%~2"=="" goto invalid_arguments
"%VENV_PYTHON%" scripts\launcher.py
set "LAUNCH_EXIT=%ERRORLEVEL%"
if not "%LAUNCH_EXIT%"=="0" goto launch_failed
exit /b 0

:invalid_arguments
echo [错误] --no-browser 不能与其他参数同时使用。
set "LAUNCH_EXIT=2"
goto launch_failed

:missing_venv
echo [ERROR] Python virtual environment .venv was not found. See README.md.
set "LAUNCH_EXIT=1"

:launch_failed
echo.
echo 启动失败。请根据上方提示处理，或查看 logs 目录中的日志。
echo 按任意键关闭窗口……
if not defined CLOUDWAVE_NO_PAUSE pause ^>nul
exit /b %LAUNCH_EXIT%
