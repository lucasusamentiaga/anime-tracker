@echo off
setlocal enabledelayedexpansion

REM Posicionarse siempre en la carpeta del .bat, independientemente de desde donde se ejecute
cd /d "%~dp0"

title Anime Tracker - Deploy a GitHub
cls
echo.
echo ==================================================================
echo          Anime Tracker - Deploy a GitHub
echo ==================================================================
echo.

REM -----------------------------------------------------------------------
REM 1. VERIFICACIONES PREVIAS
REM -----------------------------------------------------------------------

echo [1/7] Verificando entorno...

where git > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git no esta instalado.
    echo.
    start https://git-scm.com/download/win
    echo Instala Git y vuelve a ejecutar este script.
    pause
    exit /b 1
)

for /f "tokens=3" %%v in ('git --version') do set GIT_VER=%%v
echo   [OK] Git !GIT_VER! detectado

if not exist "main.py" (
    echo [ERROR] No se encuentra main.py
    echo Este script debe ejecutarse desde la carpeta raiz del proyecto.
    pause
    exit /b 1
)
echo   [OK] Carpeta del proyecto detectada

REM Comprobar si git tiene usuario configurado
set GIT_CFG_NAME=
for /f "delims=" %%n in ('git config --global user.name 2^>nul') do set GIT_CFG_NAME=%%n
if "!GIT_CFG_NAME!"=="" (
    echo.
    echo [AVISO] Git no tiene configurado tu nombre de usuario.
    set /p GIT_USER_NAME="Tu nombre: "
    set /p GIT_USER_EMAIL="Tu email de GitHub: "
    git config --global user.name "!GIT_USER_NAME!"
    git config --global user.email "!GIT_USER_EMAIL!"
    echo   [OK] Usuario configurado
)

REM -----------------------------------------------------------------------
REM 2. INICIALIZACION (PRIMERA VEZ)
REM -----------------------------------------------------------------------

echo.
echo [2/7] Verificando repositorio...

set IS_FIRST=0
if not exist ".git" (
    set IS_FIRST=1
    echo.
    echo [AVISO] Primera vez en este proyecto.
    echo.
    set /p GH_USER="Tu usuario de GitHub: "
    set /p REPO_NAME="Nombre del repositorio (Enter para 'anime-tracker'): "
    if "!REPO_NAME!"=="" set REPO_NAME=anime-tracker

    echo.
    echo IMPORTANTE: Crea el repositorio vacio en GitHub antes de continuar:
    echo   1. Se abrira el navegador en github.com/new
    echo   2. Pon nombre: !REPO_NAME!
    echo   3. Marca Public o Private
    echo   4. NO marques ninguna casilla de inicializacion
    echo   5. Pulsa Create repository
    echo.
    timeout /t 2 > nul
    start https://github.com/new
    echo.
    echo Cuando lo hayas creado, pulsa una tecla para continuar...
    pause > nul

    echo.
    echo Inicializando git...
    git init > nul 2>&1
    git branch -M main > nul 2>&1
    git remote add origin https://github.com/!GH_USER!/!REPO_NAME!.git
    echo   [OK] Repositorio configurado: !GH_USER!/!REPO_NAME!
) else (
    echo   [OK] Repositorio ya inicializado
    for /f "delims=" %%r in ('git remote get-url origin 2^>nul') do echo        Remote: %%r
)

REM -----------------------------------------------------------------------
REM 3. ANALIZAR CAMBIOS
REM -----------------------------------------------------------------------

echo.
echo [3/7] Analizando cambios...

REM Contar lineas de salida de git status --porcelain (una por archivo cambiado)
set CHANGES=0
for /f "delims=" %%i in ('git status --porcelain 2^>nul') do set /a CHANGES+=1

if !CHANGES! equ 0 (
    if !IS_FIRST! equ 0 (
        echo [AVISO] No hay cambios para subir.
        echo.
        echo Ultimos commits:
        git log --oneline -3 2>nul
        echo.
        pause
        exit /b 0
    )
)

echo   [OK] !CHANGES! archivo(s) con cambios
echo.
echo Resumen de cambios:
git status --short 2>nul

REM -----------------------------------------------------------------------
REM 4. MENSAJE DEL COMMIT
REM -----------------------------------------------------------------------

echo.
echo [4/7] Mensaje del commit

set MSG=%~1
if "%MSG%"=="" (
    echo.
    echo   Ejemplos: v1.0.0 - Release inicial
    echo             Arregla bug en notificaciones
    echo.
    set /p MSG="Mensaje del commit (Enter para 'Update'): "
    if "!MSG!"=="" set MSG=Update
)

REM -----------------------------------------------------------------------
REM 5. COMMIT
REM -----------------------------------------------------------------------

echo.
echo [5/7] Creando commit...

git add .
git commit -m "!MSG!" > nul 2>&1
if errorlevel 1 (
    if !IS_FIRST! equ 1 (
        echo   [OK] Sin cambios nuevos en primera ejecucion, continuando...
    ) else (
        echo [ERROR] No se pudo crear el commit.
        pause
        exit /b 1
    )
) else (
    echo   [OK] Commit creado: !MSG!
)

REM -----------------------------------------------------------------------
REM 6. PUSH
REM -----------------------------------------------------------------------

echo.
echo [6/7] Subiendo a GitHub...
echo.

if !IS_FIRST! equ 1 (
    git push -u origin main
) else (
    git push
)

if errorlevel 1 (
    echo.
    echo [ERROR] El push ha fallado.
    echo.
    echo Si es la primera vez, necesitas un Personal Access Token:
    timeout /t 1 > nul
    start https://github.com/settings/tokens/new
    echo.
    echo   - Note: anime-tracker-deploy
    echo   - Expiration: No expiration
    echo   - Scope: marca repo (todos los sub-permisos)
    echo   - Pulsa Generate token
    echo   - Copia el ghp_... (solo se muestra una vez)
    echo   - Vuelve a ejecutar y pega el token cuando git pida la contrasena
    echo.
    echo Para no tener que pegarlo cada vez, ejecuta:
    echo   git config --global credential.helper store
    echo.
    pause
    exit /b 1
)

echo.
echo   [OK] Subida completada

REM -----------------------------------------------------------------------
REM 7. RELEASE OPCIONAL
REM -----------------------------------------------------------------------

echo.
echo [7/7] Release (opcional)
echo.
set /p DO_RELEASE="Crear una nueva release con tag? (s/N): "
if /i "!DO_RELEASE!"=="s" (
    echo.
    echo Formato recomendado: vMAYOR.MENOR.PARCHE  ejemplo: v1.0.0
    set /p TAG="Tag de la version: "

    if "!TAG!"=="" (
        echo [AVISO] Sin tag, saltando release.
    ) else (
        set /p TAG_MSG="Descripcion de la release (Enter para 'Release !TAG!'): "
        if "!TAG_MSG!"=="" set TAG_MSG=Release !TAG!

        git tag -a !TAG! -m "!TAG_MSG!"
        if errorlevel 1 (
            echo [ERROR] El tag !TAG! ya existe o fallo la creacion.
        ) else (
            git push origin !TAG!
            if errorlevel 1 (
                echo [ERROR] No se pudo subir el tag.
            ) else (
                echo   [OK] Tag !TAG! subido.
                for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do (
                    set RELEASE_URL=%%u
                    set RELEASE_URL=!RELEASE_URL:.git=!
                    echo.
                    echo Abriendo pagina de release en GitHub...
                    timeout /t 1 > nul
                    start "" "!RELEASE_URL!/releases/new?tag=!TAG!"
                )
            )
        )
    )
)

REM -----------------------------------------------------------------------
REM RESUMEN FINAL
REM -----------------------------------------------------------------------

echo.
echo ==================================================================
echo                   DEPLOY COMPLETADO
echo ==================================================================
echo.

for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do (
    set REPO_URL=%%u
    set REPO_URL=!REPO_URL:.git=!
    echo Tu repositorio: !REPO_URL!
    echo.
)

if !IS_FIRST! equ 1 (
    echo Proximos pasos recomendados:
    echo   1. Anade Topics en Settings de GitHub
    echo      (anime, tracker, python, fastapi, desktop-app)
    echo   2. Sube screenshots al README
    echo   3. Haz Pin al repo en tu perfil
    echo.
    set /p OPEN_REPO="Abrir el repositorio en el navegador? (S/n): "
    if /i not "!OPEN_REPO!"=="n" (
        for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do (
            set OPEN_URL=%%u
            set OPEN_URL=!OPEN_URL:.git=!
            start "" "!OPEN_URL!"
        )
    )
)

echo.
echo Ultimos commits:
git log --oneline -5 2>nul
echo.
pause
