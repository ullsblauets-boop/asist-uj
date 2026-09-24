@echo off
rem Lanza UJI Study Assistant (se abre en el navegador)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Primero instala: py -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m uji_sync %*
if errorlevel 1 pause
