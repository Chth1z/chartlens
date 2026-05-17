@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-intelligent-ocr.ps1" %*
set "EYEX_EXIT_CODE=%ERRORLEVEL%"
if not "%EYEX_NO_PAUSE%"=="1" (
  echo.
  if not "%EYEX_EXIT_CODE%"=="0" echo install-ocr.cmd failed with exit code %EYEX_EXIT_CODE%.
  echo Press any key to close this window.
  pause >nul
)
exit /b %EYEX_EXIT_CODE%
