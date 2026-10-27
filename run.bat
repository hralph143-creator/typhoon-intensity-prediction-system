@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 云浪智析 - 启动器
cd /d "%~dp0"
set "APP_PYTHON=%CD%\.venv\Scripts\python.exe"
if exist "%APP_PYTHON%" (
    "%APP_PYTHON%" -c "import sys;raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>&1
    if not errorlevel 1 goto python_ready
)
set "APP_PYTHON="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined APP_PYTHON set "APP_PYTHON=%%P"
if not defined APP_PYTHON goto missing_python
"%APP_PYTHON%" -c "import sys;raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>&1
if errorlevel 1 goto missing_python

:python_ready

if /i "%~1"=="--no-browser" goto launch_no_browser
"%APP_PYTHON%" scripts\launcher.py %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
if not "%LAUNCH_EXIT%"=="0" goto launch_failed
if "%~1"=="" start "" "http://127.0.0.1:5173/"
exit /b 0

:launch_no_browser
if not "%~2"=="" goto invalid_arguments
"%APP_PYTHON%" scripts\launcher.py
set "LAUNCH_EXIT=%ERRORLEVEL%"
if not "%LAUNCH_EXIT%"=="0" goto launch_failed
exit /b 0

:invalid_arguments
echo [错误] --no-browser 不能与其他参数同时使用。
set "LAUNCH_EXIT=2"
goto launch_failed

:missing_python
echo [错误] 没有找到可用的 Python 3.11 或 3.12。请修复 .venv 或安装 Python。
set "LAUNCH_EXIT=1"

:launch_failed
echo.
echo 启动失败。请根据上方提示处理，或查看 logs 目录中的日志。
echo 按任意键关闭窗口……
if not defined CLOUDWAVE_NO_PAUSE pause ^>nul
exit /b %LAUNCH_EXIT%
