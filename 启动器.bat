@echo off
title 清月的打标工具 v1.0
cd /d %%~dp0
set PYTHON=venv\Scripts\python.exe
cls
echo ============================================
echo   清月的打标工具 v1.0
echo ============================================
echo.
if not exist %PYTHON% (
    echo [FAIL] venv missing, re-extract full zip
    pause
    exit /b 1
)
echo 启动中...
echo.
%PYTHON% main.py
echo.
pause
