# Miraru - instalador sin ejecutables propios / installer without own executables
#
#   irm https://raw.githubusercontent.com/lucasusamentiaga/anime-tracker/main/install.ps1 | iex
#
# Por que existe: los .exe de Miraru aun no tienen firma digital y el Control inteligente
# de aplicaciones de Windows 11 (Smart App Control) los bloquea sin opcion de abrirlos.
# Este instalador usa solo programas firmados: Python oficial (python.org, firmado por la
# Python Software Foundation) + el codigo de Miraru. Vuelve a ejecutarlo para actualizar:
# tu lista y tu configuracion no se tocan. Tambien lo lanza el boton "Actualizar" de la app.
#
# Con Smart App Control, PowerShell puede ir en modo de lenguaje restringido (sin COM ni
# .NET): aqui solo se usan cmdlets. Los accesos directos los crea _acceso_directo.py.
# Solo caracteres ASCII: PowerShell 5.1 puede decodificar mal el resto al hacer irm | iex.
#
# Variables opcionales: MIRARU_DESTINO, MIRARU_ZIP (codigo local en .zip), MIRARU_IDIOMA
# (es/en), MIRARU_SIN_ACCESOS=1, MIRARU_SIN_ABRIR=1, MIRARU_FORZAR_PYTHON=1,
# MIRARU_PAUSA=1 (esperar antes de cerrar: lo usa la actualizacion desde la app).

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$MiraruRepo = 'lucasusamentiaga/anime-tracker'
$MiraruPython = '3.13.15'
$MiraruDestino = $env:MIRARU_DESTINO
if (-not $MiraruDestino) { $MiraruDestino = Join-Path $env:LOCALAPPDATA 'Miraru' }
$MiraruLog = Join-Path $env:TEMP 'miraru-instalacion.log'
$MiraruEs = "$PSUICulture" -like 'es*'
if ($env:MIRARU_IDIOMA) { $MiraruEs = "$($env:MIRARU_IDIOMA)" -like 'es*' }
$MiraruEtapa = 0
$MiraruEtapas = 6

function Miraru-T($es, $en) { if ($MiraruEs) { return $es } return $en }

function Miraru-Etapa($es, $en) {
    $script:MiraruEtapa++
    Write-Host ''
    Write-Host "  [$($script:MiraruEtapa)/$MiraruEtapas] $(Miraru-T $es $en)" -ForegroundColor Magenta
}

function Miraru-Paso($es, $en) {
    if ($null -eq $en) { $en = $es }
    Write-Host "      $(Miraru-T $es $en)" -ForegroundColor Cyan
}

function Miraru-Detalle($texto) { Write-Host "      $texto" -ForegroundColor DarkGray }

function Miraru-Nativo {
    # Ejecuta un programa sin que su salida de error corte el script (PowerShell 5.1
    # convierte stderr en errores con ErrorActionPreference=Stop). Devuelve la salida.
    param([string]$Exe, [string[]]$Argumentos)
    $ErrorActionPreference = 'Continue'
    $salida = & $Exe @Argumentos 2>&1
    $script:MiraruCodigo = $LASTEXITCODE
    return $salida
}

function Miraru-Descargar($url, $archivo, $que) {
    # Descarga con 3 intentos y un error que se entiende si no hay conexion.
    $detalle = ''
    foreach ($intento in 1..3) {
        try {
            Invoke-WebRequest $url -OutFile $archivo -UseBasicParsing -TimeoutSec 900
            return
        } catch {
            $detalle = "$($_.Exception.Message)"
            if ($intento -lt 3) { Start-Sleep -Seconds (3 * $intento) }
        }
    }
    Miraru-Detalle "$url -> $detalle"
    throw (Miraru-T "No se pudo descargar $que. Comprueba tu conexion a internet y vuelve a ejecutar el comando." "Could not download $que. Check your internet connection and run the command again.")
}

function Miraru-UltimaEtiqueta {
    # 1) API de GitHub. 2) Si falla (p. ej. limite de 60 consultas por hora), la pagina
    # /releases/latest redirige a /releases/tag/<version>.
    try {
        $r = Invoke-RestMethod "https://api.github.com/repos/$MiraruRepo/releases/latest" -UseBasicParsing -TimeoutSec 30
        if ($r.tag_name) { return "$($r.tag_name)" }
    } catch { Miraru-Detalle "api.github.com: $($_.Exception.Message)" }
    try {
        $w = Invoke-WebRequest "https://github.com/$MiraruRepo/releases/latest" -UseBasicParsing -TimeoutSec 30
        $url = "$($w.BaseResponse.ResponseUri)"
        if (-not $url) { $url = "$($w.BaseResponse.RequestMessage.RequestUri)" }
        if ($url -match '/releases/tag/([^/?#]+)') { return $Matches[1] }
    } catch { Miraru-Detalle "github.com: $($_.Exception.Message)" }
    throw (Miraru-T 'No se pudo conectar con GitHub para buscar la ultima version. Comprueba tu conexion a internet y vuelve a intentarlo en unos minutos.' 'Could not reach GitHub to find the latest version. Check your internet connection and try again in a few minutes.')
}

function Miraru-EspacioLibreMB {
    # Devuelve los MB libres de la unidad de destino, o $null si no se puede saber.
    try {
        $letra = Split-Path $MiraruDestino -Qualifier
        $unidad = Get-PSDrive $letra.TrimEnd(':') -ErrorAction Stop
        if ($unidad.Free) { return [int]($unidad.Free / 1MB) }
    } catch { }
    return $null
}

function Miraru-ProbarPython($exe, $previos) {
    # Devuelve la ruta real de un Python >= 3.10 con tkinter y venv (no el de la Microsoft Store).
    # sysconfig 'win-...': descarta Pythons de MSYS/MinGW, que no pueden usar las dependencias publicadas.
    $comprobar = "import sys, sysconfig, tkinter, venv; ok = sys.version_info >= (3, 10) and 'WindowsApps' not in sys.executable and sysconfig.get_platform().startswith('win'); print('MIRARU-OK' if ok else 'MIRARU-NO', sys.executable)"
    $argumentos = @()
    if ($previos) { $argumentos += $previos }
    $argumentos += @('-c', $comprobar)
    try { $salida = Miraru-Nativo $exe $argumentos } catch { return $null }
    if ($script:MiraruCodigo -ne 0) { return $null }
    foreach ($linea in $salida) {
        $texto = "$linea"
        if ($texto.StartsWith('MIRARU-OK ')) { return $texto.Substring(10).Trim() }
    }
    return $null
}

function Miraru-BuscarPython {
    $candidatos = @()
    $privado = Join-Path $MiraruDestino 'python\python.exe'
    if (Test-Path $privado) { $candidatos += , @($privado, $null) }
    foreach ($nombre in @('py', 'python', 'python3')) {
        foreach ($c in @(Get-Command $nombre -All -ErrorAction SilentlyContinue)) {
            # El "python" de WindowsApps es un alias que abre la Microsoft Store: no se toca.
            if ($c.Source -and $c.Source -notmatch 'WindowsApps') {
                if ($nombre -eq 'py') { $candidatos += , @($c.Source, '-3') }
                else { $candidatos += , @($c.Source, $null) }
            }
        }
    }
    foreach ($patron in @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe")) {
        foreach ($f in @(Get-ChildItem $patron -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            $candidatos += , @($f.FullName, $null)
        }
    }
    foreach ($c in $candidatos) {
        $ruta = Miraru-ProbarPython $c[0] $c[1]
        if ($ruta) { return $ruta }
    }
    return $null
}

function Miraru-InstalarPython {
    # Python privado de Miraru a partir de los paquetes MSI oficiales (firmados por la PSF),
    # extraidos con msiexec /a. No se usa el instalador python-X.exe: su motor extrae una
    # DLL sin firma (PythonBA.dll) que Smart App Control bloquea y el instalador se cuelga.
    # Sin registro ni entrada en "Aplicaciones": vive en <Miraru>\python y se borra con Miraru.
    $carpeta = Join-Path $MiraruDestino 'python'
    $temporal = Join-Path $env:TEMP ('miraru-python-' + (Get-Random))
    New-Item -ItemType Directory -Force $temporal | Out-Null
    Remove-Item $carpeta -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $carpeta | Out-Null
    Miraru-Paso "Descargando Python $MiraruPython oficial de python.org (unos 30 MB)..." "Downloading official Python $MiraruPython from python.org (about 30 MB)..."
    foreach ($m in @('core', 'exe', 'lib', 'tcltk')) {
        $msi = Join-Path $temporal "$m.msi"
        Miraru-Descargar "https://www.python.org/ftp/python/$MiraruPython/amd64/$m.msi" $msi "Python ($m.msi)"
        $firma = Get-AuthenticodeSignature $msi
        if ("$($firma.Status)" -ne 'Valid' -or "$($firma.SignerCertificate.Subject)" -notmatch 'Python Software Foundation') {
            Remove-Item $temporal -Recurse -Force -ErrorAction SilentlyContinue
            throw (Miraru-T "El paquete $m.msi de Python no tiene una firma valida de la Python Software Foundation: no se usara." "Python package $m.msi is not validly signed by the Python Software Foundation: it will not be used.")
        }
    }
    Miraru-Paso 'Firma de la Python Software Foundation comprobada. Preparando Python (sin permisos de administrador)...' 'Python Software Foundation signature verified. Setting up Python (no administrator rights needed)...'
    foreach ($m in @('core', 'exe', 'lib', 'tcltk')) {
        $msi = Join-Path $temporal "$m.msi"
        $p = Start-Process 'msiexec.exe' -PassThru -ArgumentList @('/a', "`"$msi`"", "TARGETDIR=`"$carpeta`"", '/qn')
        Wait-Process -Id $p.Id -Timeout 300 -ErrorAction SilentlyContinue
        if (-not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            throw (Miraru-T "Windows no termino de extraer $m.msi en 5 minutos." "Windows did not finish extracting $m.msi within 5 minutes.")
        }
        if ($p.ExitCode -ne 0) { throw (Miraru-T "No se pudo extraer $m.msi (codigo $($p.ExitCode))." "Could not extract $m.msi (code $($p.ExitCode)).") }
    }
    # msiexec /a deja una copia de cada .msi junto a los archivos
    Get-ChildItem $carpeta -Filter '*.msi' | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item $temporal -Recurse -Force -ErrorAction SilentlyContinue
    $ruta = Miraru-ProbarPython (Join-Path $carpeta 'python.exe') $null
    if (-not $ruta) { throw (Miraru-T 'Python se ha preparado pero no responde (puede que Windows lo este bloqueando).' 'Python was set up but does not respond (Windows may be blocking it).') }
    return $ruta
}

function Miraru-PrepararEntorno($python) {
    $venv = Join-Path $MiraruDestino '.venv'
    $vpy = Join-Path $venv 'Scripts\python.exe'
    if (Test-Path $vpy) {
        Miraru-Nativo $vpy @('-c', 'import sys, tkinter') | Out-Null
        if ($script:MiraruCodigo -ne 0) { Remove-Item $venv -Recurse -Force }
    }
    if (-not (Test-Path $vpy)) {
        Miraru-Paso 'Creando el entorno de Miraru...' 'Creating the Miraru environment...'
        $salida = Miraru-Nativo $python @('-m', 'venv', $venv)
        if ($script:MiraruCodigo -ne 0) { $salida | Select-Object -Last 10 | ForEach-Object { Miraru-Detalle "$_" }; return $false }
    }
    Miraru-Paso 'Instalando componentes (la primera vez tarda 1-3 minutos; luego, segundos)...' 'Installing components (1-3 minutes the first time; seconds afterwards)...'
    $salida = Miraru-Nativo $vpy @('-m', 'pip', 'install', '--disable-pip-version-check',
        '--no-warn-script-location', '-q', '-r', (Join-Path $MiraruDestino 'requirements.txt'))
    if ($script:MiraruCodigo -ne 0) {
        $salida | Select-Object -Last 15 | ForEach-Object { Miraru-Detalle "$_" }
        return $false
    }
    return $true
}

function Miraru-VersionInstalada {
    $core = Join-Path $MiraruDestino 'core.py'
    if (-not (Test-Path $core)) { return $null }
    $texto = Get-Content $core -Raw
    if ($texto -match 'VERSION\s*=\s*"([^"]+)"') { return $Matches[1] }
    return $null
}

function Miraru-Recuadro($lineas, $color) {
    $ancho = 60
    foreach ($l in $lineas) { if ($l.Length + 4 -gt $ancho) { $ancho = $l.Length + 4 } }
    $borde = '  +' + ('-' * $ancho) + '+'
    Write-Host ''
    Write-Host $borde -ForegroundColor $color
    foreach ($l in $lineas) { Write-Host ('  |  ' + $l.PadRight($ancho - 2) + '|') -ForegroundColor $color }
    Write-Host $borde -ForegroundColor $color
}

function Miraru-Instalar {
    Write-Host ''
    Write-Host '  Miraru' -ForegroundColor Magenta -NoNewline
    Write-Host (Miraru-T ' - instalacion y actualizacion' ' - install and update')
    Write-Host "  $(Miraru-T 'Carpeta' 'Folder'): $MiraruDestino" -ForegroundColor DarkGray
    Write-Host "  $(Miraru-T 'No cierres esta ventana hasta que termine.' 'Do not close this window until it finishes.')" -ForegroundColor DarkGray

    # 1. Comprobaciones previas y cerrar Miraru si esta abierto.
    Miraru-Etapa 'Comprobando el equipo' 'Checking this computer'
    $anterior = Miraru-VersionInstalada
    if ($anterior) { Miraru-Paso "Version instalada: $anterior" "Installed version: $anterior" }
    $libreMB = Miraru-EspacioLibreMB
    $necesarioMB = 150
    if (-not (Test-Path (Join-Path $MiraruDestino '.venv'))) { $necesarioMB = 500 }
    if ($null -ne $libreMB -and $libreMB -lt $necesarioMB) {
        throw (Miraru-T "No hay espacio suficiente en el disco: quedan $libreMB MB y Miraru necesita unos $necesarioMB MB. Libera espacio y vuelve a intentarlo." "Not enough disk space: $libreMB MB free and Miraru needs about $necesarioMB MB. Free some space and try again.")
    }
    try {
        Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/apagar' -TimeoutSec 3 | Out-Null
        Miraru-Paso 'Cerrando Miraru para poder actualizarlo...' 'Closing Miraru so it can be updated...'
        Start-Sleep -Seconds 3
    } catch { }

    # 2. Codigo de la ultima version publicada.
    $etiqueta = 'local'
    $zip = $env:MIRARU_ZIP
    $borrarZip = $false
    if (-not $zip) {
        Miraru-Etapa 'Descargando Miraru' 'Downloading Miraru'
        $etiqueta = Miraru-UltimaEtiqueta
        if ($anterior -and $etiqueta.TrimStart('v') -eq $anterior) {
            Miraru-Paso "Ya tienes la ultima version ($etiqueta): se reinstala para reparar lo que falte." "You already have the latest version ($etiqueta): reinstalling to repair anything missing."
        } else {
            Miraru-Paso "Ultima version: $etiqueta" "Latest version: $etiqueta"
        }
        $zip = Join-Path $env:TEMP "miraru-$etiqueta.zip"
        Miraru-Descargar "https://github.com/$MiraruRepo/archive/refs/tags/$etiqueta.zip" $zip "Miraru $etiqueta"
        $borrarZip = $true
    } else {
        Miraru-Etapa 'Preparando Miraru (copia local)' 'Preparing Miraru (local copy)'
    }
    $temporal = Join-Path $env:TEMP ('miraru-codigo-' + (Get-Random))
    # tar.exe de Windows (firmado por Microsoft) en vez de Expand-Archive: ese modulo no
    # carga en modo de lenguaje restringido. Ruta completa: el tar de Git no abre .zip.
    New-Item -ItemType Directory -Force $temporal | Out-Null
    $salida = Miraru-Nativo (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xf', $zip, '-C', $temporal)
    if ($script:MiraruCodigo -ne 0) {
        $salida | Select-Object -Last 5 | ForEach-Object { Miraru-Detalle "$_" }
        throw (Miraru-T 'No se pudo descomprimir Miraru (la descarga puede estar incompleta). Vuelve a ejecutar el comando.' 'Could not unpack Miraru (the download may be incomplete). Run the command again.')
    }
    $origen = @(Get-ChildItem $temporal -Directory)[0].FullName

    # 3. Copiar archivos (sin tocar la lista ni la configuracion).
    Miraru-Etapa 'Copiando archivos (tu lista y tu configuracion no se tocan)' 'Copying files (your list and settings are kept)'
    New-Item -ItemType Directory -Force $MiraruDestino | Out-Null
    $primeraVez = -not (Test-Path (Join-Path $MiraruDestino 'launcher.py'))
    $omitir = @('mobile-expo', 'tests', 'skills', 'screenshots', '.github', 'hooks', 'packaging')
    Get-ChildItem $origen -Force | Where-Object { $omitir -notcontains $_.Name } | ForEach-Object {
        Copy-Item $_.FullName -Destination $MiraruDestino -Recurse -Force
    }
    Remove-Item $temporal -Recurse -Force -ErrorAction SilentlyContinue
    if ($borrarZip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }

    # Datos de una instalacion anterior con el instalador .exe (carpeta AnimeTracker).
    $viejo = Join-Path $env:LOCALAPPDATA 'AnimeTracker'
    if ($primeraVez -and -not (Test-Path (Join-Path $MiraruDestino 'anime_tracker.db')) -and (Test-Path (Join-Path $viejo 'anime_tracker.db'))) {
        Miraru-Paso 'Recuperando tu lista de la instalacion anterior (AnimeTracker)...' 'Bringing over your list from the previous install (AnimeTracker)...'
        foreach ($f in @('anime_tracker.db', 'anime_tracker.db-wal', 'anime_tracker.db-shm', 'credentials.json')) {
            $o = Join-Path $viejo $f
            if (Test-Path $o) { Copy-Item $o -Destination $MiraruDestino -Force }
        }
    }

    # 4. Python firmado.
    Miraru-Etapa 'Python (el motor de Miraru)' 'Python (the engine behind Miraru)'
    $python = $null
    if (-not $env:MIRARU_FORZAR_PYTHON) {
        Miraru-Paso 'Buscando un Python 3.10 o superior en este equipo...' 'Looking for Python 3.10 or newer on this computer...'
        $python = Miraru-BuscarPython
    }
    $propio = $false
    if (-not $python) {
        Miraru-Paso 'Se prepara un Python solo para Miraru (1-2 minutos).' 'Setting up a Python just for Miraru (1-2 minutes).'
        $python = Miraru-InstalarPython
        $propio = $true
    }
    Miraru-Detalle "Python: $python"

    # 5. Componentes (dependencias de Python).
    Miraru-Etapa 'Componentes de Miraru' 'Miraru components'
    $fallo = Miraru-T 'No se pudieron instalar los componentes de Miraru. Comprueba tu conexion a internet y vuelve a ejecutar el comando.' 'Could not install the Miraru components. Check your internet connection and run the command again.'
    if (-not (Miraru-PrepararEntorno $python)) {
        if ($propio) { throw $fallo }
        # El Python que ya tenias no sirve (p. ej. demasiado nuevo para alguna dependencia):
        # se usa el oficial recomendado.
        Miraru-Paso 'El Python de este equipo no sirve; se prepara el recomendado (1-2 minutos).' 'The Python on this computer does not work; setting up the recommended one (1-2 minutes).'
        Remove-Item (Join-Path $MiraruDestino '.venv') -Recurse -Force -ErrorAction SilentlyContinue
        $python = Miraru-InstalarPython
        if (-not (Miraru-PrepararEntorno $python)) { throw $fallo }
    }

    # 6. Marca de instalacion, accesos directos y entrada en "Aplicaciones instaladas".
    Miraru-Etapa 'Accesos directos y registro en Windows' 'Shortcuts and Windows registration'
    $pythonw = Join-Path $MiraruDestino '.venv\Scripts\pythonw.exe'
    $vpy = Join-Path $MiraruDestino '.venv\Scripts\python.exe'
    $launcher = Join-Path $MiraruDestino 'launcher.py'
    Set-Content (Join-Path $MiraruDestino '.miraru-instalado') "install.ps1 $etiqueta" -Encoding UTF8
    $version = Miraru-VersionInstalada
    if (-not $version) { $version = $etiqueta.TrimStart('v') }

    if (-not $env:MIRARU_SIN_ACCESOS) {
        Miraru-Paso 'Menu Inicio y escritorio...' 'Start menu and desktop...'
        $salida = Miraru-Nativo $vpy @((Join-Path $MiraruDestino '_acceso_directo.py'), $MiraruDestino)
        $salida | ForEach-Object { Miraru-Detalle "$_" }

        $clave = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Miraru'
        New-Item $clave -Force | Out-Null
        $valores = @{
            DisplayName = 'Miraru'; DisplayVersion = $version; Publisher = 'lucasusamentiaga'
            DisplayIcon = (Join-Path $MiraruDestino 'static\icon.ico'); InstallLocation = $MiraruDestino
            UninstallString = "`"$pythonw`" `"$launcher`" --uninstall"
            URLInfoAbout = "https://github.com/$MiraruRepo"
        }
        foreach ($k in $valores.Keys) { New-ItemProperty $clave -Name $k -Value $valores[$k] -PropertyType String -Force | Out-Null }
        New-ItemProperty $clave -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
        New-ItemProperty $clave -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
        Miraru-Paso 'Miraru aparece en Configuracion > Aplicaciones (desde ahi se desinstala).' 'Miraru is listed in Settings > Apps (uninstall it from there).'
    }

    $titulo = Miraru-T "Miraru $version esta listo" "Miraru $version is ready"
    if ($anterior -and $anterior -ne $version) { $titulo = Miraru-T "Miraru actualizado: $anterior -> $version" "Miraru updated: $anterior -> $version" }
    Miraru-Recuadro @(
        $titulo,
        '',
        (Miraru-T 'Abrelo con el icono "Miraru" del menu Inicio o del escritorio.' 'Open it with the "Miraru" icon in the Start menu or on the desktop.'),
        (Miraru-T 'Para actualizar: boton "Actualizar" en la app o este comando.' 'To update: the "Update" button in the app or this command.')
    ) 'Green'

    # Aviso si sigue instalada la version antigua con .exe (AnimeTracker).
    foreach ($raiz in @('HKCU:', 'HKLM:')) {
        if (Test-Path "$raiz\Software\Microsoft\Windows\CurrentVersion\Uninstall\AnimeTracker") {
            Write-Host ''
            Write-Host "  $(Miraru-T 'Tambien tienes la version antigua (AnimeTracker). Tu lista ya esta en Miraru;' 'You also have the old version (AnimeTracker). Your list is already in Miraru;')" -ForegroundColor Yellow
            Write-Host "  $(Miraru-T 'puedes desinstalarla en Configuracion > Aplicaciones > AnimeTracker.' 'you can uninstall it in Settings > Apps > AnimeTracker.')" -ForegroundColor Yellow
            break
        }
    }
    Write-Host ''
    if (-not $env:MIRARU_SIN_ABRIR) {
        Start-Process $pythonw -ArgumentList "`"$launcher`"" -WorkingDirectory $MiraruDestino
    }
}

$MiraruTranscripcion = $false
try { Start-Transcript -Path $MiraruLog -Force | Out-Null; $MiraruTranscripcion = $true } catch { }
$MiraruOk = $false
try {
    Miraru-Instalar
    $MiraruOk = $true
} catch {
    Miraru-Recuadro @(
        (Miraru-T 'No se pudo instalar Miraru' 'Miraru could not be installed'),
        '',
        "$($_.Exception.Message)"
    ) 'Red'
    Write-Host ''
    Write-Host "  $(Miraru-T 'Registro de la instalacion' 'Install log'): $MiraruLog" -ForegroundColor DarkGray
    Write-Host "  $(Miraru-T 'Si vuelve a pasar, abre un aviso adjuntando ese archivo:' 'If it happens again, open an issue and attach that file:')"
    Write-Host "  https://github.com/$MiraruRepo/issues"
    Write-Host ''
}
if ($MiraruTranscripcion) {
    try { Stop-Transcript | Out-Null } catch { }
    if ($MiraruOk -and (Test-Path $MiraruDestino)) {
        Copy-Item $MiraruLog (Join-Path $MiraruDestino 'instalacion.log') -Force -ErrorAction SilentlyContinue
    }
}
if ($env:MIRARU_PAUSA) {
    if ($MiraruOk) { Start-Sleep -Seconds 5 }
    else { Read-Host (Miraru-T '  Pulsa Enter para cerrar' '  Press Enter to close') | Out-Null }
}
