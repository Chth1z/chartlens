@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\start-ocr-sidecar.ps1" %*
