@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\connect_firebase.ps1"
if errorlevel 1 pause
