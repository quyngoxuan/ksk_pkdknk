@echo off
setlocal
title KSK API - Port 5500

REM Always run from the directory containing this file.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [LOI] Khong tim thay virtual environment: .venv\Scripts\python.exe
  echo Hay tao lai moi truong theo caidat.txt truoc khi chay file nay.
  echo.
  pause
  exit /b 1
)

echo.
echo Dang khoi dong KSK API tai http://localhost:5500
echo Swagger: http://localhost:5500/docs
echo Nhan Ctrl+C de dung API.
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 5500
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo [LOI] API dung voi ma %EXIT_CODE%.
  echo Neu bao loi port 5500 da duoc su dung, hay dung tien trinh API cu truoc.
)
pause
exit /b %EXIT_CODE%
