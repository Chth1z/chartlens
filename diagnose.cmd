@echo off
setlocal
pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\diagnose.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EXIT_CODE%"=="0" echo Diagnose failed with exit code %EXIT_CODE%.
if /I not "%EYES_NO_PAUSE%"=="1" pause
endlocal & exit /b %EXIT_CODE%
