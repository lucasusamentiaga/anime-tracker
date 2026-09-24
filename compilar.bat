@echo off
setlocal enabledelayedexpansion
title Anime Tracker - Compilador
cd /d "%~dp0"

echo.
echo  ============================================================
echo   Anime Tracker - Generador de instalador
echo   Compatible con Python 3.9, 3.10, 3.11, 3.12, 3.13, 3.14
echo  ============================================================
echo.

:: PYEXE  = ruta o comando para ejecutar Python
:: PYCMD  = 1 si es comando simple (py/python/python3), 0 si es ruta completa
set "PYEXE="
set "PYCMD=0"
set "PYCMD_PY=0"

:: ---- Metodo 1: py launcher (el mas fiable en Windows) -----------------------
where py >nul 2>&1
if %errorlevel% equ 0 (
    py --version >nul 2>&1
    if !errorlevel! equ 0 ( set "PYEXE=py" & set "PYCMD=1" & goto :check_version )
)

:: ---- Metodo 2: python en PATH -----------------------------------------------
where python >nul 2>&1
if %errorlevel% equ 0 (
    python --version >nul 2>&1
    if !errorlevel! equ 0 ( set "PYEXE=python" & set "PYCMD=1" & goto :check_version )
)

:: ---- Metodo 3: python3 en PATH ----------------------------------------------
where python3 >nul 2>&1
if %errorlevel% equ 0 (
    python3 --version >nul 2>&1
    if !errorlevel! equ 0 ( set "PYEXE=python3" & set "PYCMD=1" & goto :check_version )
)

:: ---- Metodo 4: AppData\Programs\Python (instalacion desde python.org) -------
call :probar "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
call :probar "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :probar "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :probar "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
call :probar "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
call :probar "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
call :probar "%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
if defined PYEXE goto :check_version

:: ---- Metodo 5: C:\PythonXXX -------------------------------------------------
call :probar "C:\Python314\python.exe"
call :probar "C:\Python313\python.exe"
call :probar "C:\Python312\python.exe"
call :probar "C:\Python311\python.exe"
call :probar "C:\Python310\python.exe"
call :probar "C:\Python39\python.exe"
call :probar "C:\Python38\python.exe"
if defined PYEXE goto :check_version

:: ---- Metodo 6: C:\Program Files\PythonXXX -----------------------------------
call :probar "C:\Program Files\Python314\python.exe"
call :probar "C:\Program Files\Python313\python.exe"
call :probar "C:\Program Files\Python312\python.exe"
call :probar "C:\Program Files\Python311\python.exe"
call :probar "C:\Program Files\Python310\python.exe"
call :probar "C:\Program Files\Python39\python.exe"
call :probar "C:\Program Files\Python38\python.exe"
if defined PYEXE goto :check_version

:: ---- Metodo 7: Conda/Miniconda/Anaconda/Miniforge ---------------------------
call :probar "%USERPROFILE%\miniconda3\python.exe"
call :probar "%USERPROFILE%\Miniconda3\python.exe"
call :probar "%USERPROFILE%\anaconda3\python.exe"
call :probar "%USERPROFILE%\Anaconda3\python.exe"
call :probar "%USERPROFILE%\miniforge3\python.exe"
call :probar "%USERPROFILE%\Miniforge3\python.exe"
call :probar "C:\ProgramData\miniconda3\python.exe"
call :probar "C:\ProgramData\anaconda3\python.exe"
call :probar "C:\tools\miniconda3\python.exe"
if defined PYEXE goto :check_version

:: ---- Metodo 8: buscar en subcarpetas de AppData\Programs\Python -------------
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        if not defined PYEXE (
            set "PYEXE=%%D\python.exe"
            set "PYCMD=0"
        )
    )
)
if defined PYEXE goto :check_version

:: ---- NO ENCONTRADO ----------------------------------------------------------
echo.
echo  *** ERROR: Python no encontrado en el sistema ***
echo.
echo  Instala Python desde alguna de estas opciones:
echo.
echo   1. https://www.python.org/downloads/
echo      Importante: marca "Add Python to PATH" al instalar
echo.
echo   2. Microsoft Store: busca "Python 3.11"
echo.
echo   3. Miniconda: https://docs.conda.io/miniconda.html
echo.
echo  Una vez instalado, cierra esta ventana y abre compilar.bat
echo  de nuevo.
echo.
pause
exit /b 1


:check_version
:: ---- Verificar que el ejecutable funciona -----------------------------------
if "!PYCMD!"=="1" (
    !PYEXE! --version >nul 2>&1
) else (
    "!PYEXE!" --version >nul 2>&1
)
if %errorlevel% neq 0 (
    echo  ERROR: !PYEXE! no responde.
    echo  Intenta ejecutar compilar.bat como Administrador.
    pause
    exit /b 1
)

echo  Python encontrado: !PYEXE!
if "!PYCMD!"=="1" ( !PYEXE! --version ) else ( "!PYEXE!" --version )
echo.

:: Verificar version >= 3.9
if "!PYCMD!"=="1" (
    !PYEXE! -c "import sys; exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
) else (
    "!PYEXE!" -c "import sys; exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
)
if %errorlevel% neq 0 (
    echo  ERROR: Se requiere Python 3.9 o superior.
    if "!PYCMD!"=="1" ( !PYEXE! --version ) else ( "!PYEXE!" --version )
    pause
    exit /b 1
)
echo  Version compatible.
echo.


:: ---- Entorno virtual --------------------------------------------------------
if exist venv\Scripts\python.exe (
    echo  Reutilizando entorno virtual existente...
    call venv\Scripts\activate.bat >nul 2>&1
    set "PY=python"
    set "PYCMD_PY=1"
) else (
    echo  Creando entorno virtual...
    if "!PYCMD!"=="1" (
        !PYEXE! -m venv venv
    ) else (
        "!PYEXE!" -m venv venv
    )
    if !errorlevel! neq 0 (
        echo  No se pudo crear venv. Usando Python del sistema directamente...
        set "PY=!PYEXE!"
        set "PYCMD_PY=!PYCMD!"
        goto :deps
    )
    call venv\Scripts\activate.bat >nul 2>&1
    set "PY=python"
    set "PYCMD_PY=1"
)
echo  Entorno listo.
echo.


:deps
:: ---- Instalar dependencias --------------------------------------------------
echo  Actualizando pip...
if "!PYCMD_PY!"=="1" (
    !PY! -m pip install --upgrade pip --quiet --disable-pip-version-check >nul 2>&1
) else (
    "!PY!" -m pip install --upgrade pip --quiet --disable-pip-version-check >nul 2>&1
)

echo  Instalando dependencias (puede tardar unos minutos)...
if "!PYCMD_PY!"=="1" (
    !PY! -m pip install -r requirements.txt --quiet --disable-pip-version-check
) else (
    "!PY!" -m pip install -r requirements.txt --quiet --disable-pip-version-check
)
if %errorlevel% neq 0 (
    echo  Reintentando con metodo alternativo...
    if "!PYCMD_PY!"=="1" (
        !PY! -m pip install -r requirements.txt --no-build-isolation
    ) else (
        "!PY!" -m pip install -r requirements.txt --no-build-isolation
    )
    if !errorlevel! neq 0 (
        echo  ERROR al instalar dependencias. Comprueba tu conexion a internet.
        pause
        exit /b 1
    )
)

echo  Instalando Pillow y lxml...
if "!PYCMD_PY!"=="1" (
    !PY! -m pip install Pillow lxml --quiet --disable-pip-version-check >nul 2>&1
) else (
    "!PY!" -m pip install Pillow lxml --quiet --disable-pip-version-check >nul 2>&1
)

echo  Dependencias OK.
echo.


:: ---- Compilar ---------------------------------------------------------------
echo  Compilando AnimeTracker-Setup.exe...
echo  (la primera vez puede tardar 5-10 minutos, por favor espera)
echo.

if "!PYCMD_PY!"=="1" (
    !PY! build.py
) else (
    "!PY!" build.py
)
if %errorlevel% neq 0 (
    echo.
    echo  ERROR en la compilacion.
    echo  Lee los mensajes anteriores para ver que ha fallado.
    pause
    exit /b 1
)

echo.
if exist dist\AnimeTracker-Setup.exe (
    echo  ============================================================
    echo   LISTO: dist\AnimeTracker-Setup.exe
    echo  ============================================================
    echo.
    explorer dist
)
pause
exit /b 0


:: =============================================================================
:: SUBRUTINA :probar
:: Recibe %1 = ruta entre comillas.
:: Si el archivo existe y Python responde, guarda en PYEXE (sin comillas).
:: =============================================================================
:probar
if defined PYEXE exit /b 0
if exist %1 (
    %1 --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYEXE=%~1"
        set "PYCMD=0"
    )
)
exit /b 0
