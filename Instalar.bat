@echo off
rem Instala (o actualiza) UJI Study Assistant. Doble clic y esperar.
cd /d "%~dp0"
echo.
echo === Instalando UJI Study Assistant en: %CD%
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo No encuentro Python. Instalalo desde https://www.python.org/downloads/
  echo marcando la casilla "Add python.exe to PATH", y vuelve a abrir este archivo.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo [1/2] Creando el entorno...
  py -m venv .venv
  if errorlevel 1 (
    echo Error al crear el entorno.
    pause
    exit /b 1
  )
)
echo [2/2] Instalando lo necesario (tarda unos minutos)...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Ha habido un error. Haz una foto de esta ventana y enviasela a Claude.
  pause
  exit /b 1
)
echo.
echo === Listo. Ahora abre "UJI Study Assistant.bat" ===
pause
