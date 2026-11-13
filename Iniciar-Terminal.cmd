@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Iniciar-Windows.ps1" -Terminal %*
if errorlevel 1 pause
