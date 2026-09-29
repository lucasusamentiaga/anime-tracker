# Miraru - instalador sin ejecutables propios
#
#   irm https://raw.githubusercontent.com/lucasusamentiaga/anime-tracker/main/install.ps1 | iex
#
# Por que existe: los .exe de Miraru aun no tienen firma digital y el Control inteligente
# de aplicaciones de Windows 11 (Smart App Control) los bloquea sin opcion de abrirlos.
# Este instalador usa solo programas firmados: Python oficial (python.org, firmado por la
# Python Software Foundation) + el codigo de Miraru. Vuelve a ejecutarlo para actualizar:
# tu lista y tu configuracion no se tocan.
#
# Con Smart App Control, PowerShell va en modo de lenguaje restringido (sin COM ni .NET):
# aqui solo se usan cmdlets. Los accesos directos los crea _acceso_directo.py.
#
# Variables opcionales (pruebas): MIRARU_DESTINO, MIRARU_ZIP (codigo local en .zip),
# MIRARU_SIN_ACCESOS=1, MIRARU_SIN_ABRIR=1, MIRARU_FORZAR_PYTHON=1.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$MiraruRepo = 'lucasusamentiaga/anime-tracker'
$MiraruPython = '3.13.15'
$MiraruDestino = $env:MIRARU_DESTINO
if (-not $MiraruDestino) { $MiraruDestino = Join-Path $env:LOCALAPPDATA 'Miraru' }

function Miraru-Paso($texto) { Write-Host "  > $texto" -ForegroundColor Cyan }

function Miraru-Nativo {
    # Ejecuta un programa sin que su salida de error corte el script (PowerShell 5.1
    # convierte stderr en errores con ErrorActionPreference=Stop). Devuelve la salida.
    param([string]$Exe, [string[]]$Argumentos)
    $ErrorActionPreference = 'Continue'
    $salida = & $Exe @Argumentos 2>&1
    $script:MiraruCodigo = $LASTEXITCODE
    return $salida
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
    Miraru-Paso "Descargando Python $MiraruPython oficial (python.org)..."
    $url = "https://www.python.org/ftp/python/$MiraruPython/python-$MiraruPython-amd64.exe"
    $exe = Join-Path $env:TEMP "python-$MiraruPython-amd64.exe"
    Invoke-WebRequest $url -OutFile $exe -UseBasicParsing
    $firma = Get-AuthenticodeSignature $exe
    if ("$($firma.Status)" -ne 'Valid' -or "$($firma.SignerCertificate.Subject)" -notmatch 'Python Software Foundation') {
        Remove-Item $exe -Force -ErrorAction SilentlyContinue
        throw 'El instalador de Python descargado no tiene una firma valida de la Python Software Foundation.'
    }
    Miraru-Paso 'Instalando Python solo para tu usuario (no necesita permisos de administrador)...'
    $p = Start-Process $exe -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0', 'Include_test=0',
        'Include_doc=0', 'Shortcuts=0', 'AssociateFiles=0')
    # Si Windows bloquea parte del instalador, este puede quedarse esperando para siempre.
    Wait-Process -Id $p.Id -Timeout 600 -ErrorAction SilentlyContinue
    if (-not $p.HasExited) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        throw 'La instalacion de Python no termino en 10 minutos (puede que Windows la este bloqueando). Instala Python 3.13 desde python.org y vuelve a ejecutar este comando.'
    }
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "La instalacion de Python ha fallado (codigo $($p.ExitCode))." }
    $carpeta = 'Python' + ($MiraruPython -replace '^(\d+)\.(\d+)\..*$', '$1$2')
    $ruta = Miraru-ProbarPython (Join-Path $env:LOCALAPPDATA "Programs\Python\$carpeta\python.exe") $null
    if (-not $ruta) { throw 'Python se ha instalado pero no responde.' }
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
        Miraru-Paso 'Creando el entorno de Miraru...'
        $salida = Miraru-Nativo $python @('-m', 'venv', $venv)
        if ($script:MiraruCodigo -ne 0) { $salida | Select-Object -Last 10 | ForEach-Object { Write-Host "    $_" }; return $false }
    }
    Miraru-Paso 'Instalando dependencias (la primera vez tarda un par de minutos)...'
    $salida = Miraru-Nativo $vpy @('-m', 'pip', 'install', '--disable-pip-version-check',
        '--no-warn-script-location', '-q', '-r', (Join-Path $MiraruDestino 'requirements.txt'))
    if ($script:MiraruCodigo -ne 0) {
        $salida | Select-Object -Last 15 | ForEach-Object { Write-Host "    $_" }
        return $false
    }
    return $true
}

function Miraru-Instalar {
    Write-Host ''
    Write-Host '  Miraru - instalacion' -ForegroundColor Magenta
    Write-Host "  Carpeta: $MiraruDestino"
    Write-Host ''

    # 1. Cerrar Miraru si esta abierto (para poder actualizar sus archivos).
    try {
        Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/apagar' -TimeoutSec 3 | Out-Null
        Miraru-Paso 'Cerrando Miraru para actualizarlo...'
        Start-Sleep -Seconds 3
    } catch { }

    # 2. Codigo de la ultima version publicada.
    $etiqueta = 'local'
    $zip = $env:MIRARU_ZIP
    $borrarZip = $false
    if (-not $zip) {
        Miraru-Paso 'Buscando la ultima version...'
        $release = Invoke-RestMethod "https://api.github.com/repos/$MiraruRepo/releases/latest" -UseBasicParsing
        $etiqueta = "$($release.tag_name)"
        Miraru-Paso "Descargando Miraru $etiqueta..."
        $zip = Join-Path $env:TEMP "miraru-$etiqueta.zip"
        Invoke-WebRequest "https://github.com/$MiraruRepo/archive/refs/tags/$etiqueta.zip" -OutFile $zip -UseBasicParsing
        $borrarZip = $true
    }
    $temporal = Join-Path $env:TEMP ('miraru-codigo-' + (Get-Random))
    # tar.exe de Windows (firmado por Microsoft) en vez de Expand-Archive: ese modulo no
    # carga en modo de lenguaje restringido. Ruta completa: el tar de Git no abre .zip.
    New-Item -ItemType Directory -Force $temporal | Out-Null
    $salida = Miraru-Nativo (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xf', $zip, '-C', $temporal)
    if ($script:MiraruCodigo -ne 0) { $salida | Select-Object -Last 5 | ForEach-Object { Write-Host "    $_" }; throw 'No se pudo descomprimir Miraru.' }
    $origen = @(Get-ChildItem $temporal -Directory)[0].FullName

    Miraru-Paso 'Copiando archivos...'
    New-Item -ItemType Directory -Force $MiraruDestino | Out-Null
    $primeraVez = -not (Test-Path (Join-Path $MiraruDestino 'launcher.py'))
    $omitir = @('mobile-expo', 'tests', 'skills', 'screenshots', '.github', 'hooks', 'packaging')
    Get-ChildItem $origen -Force | Where-Object { $omitir -notcontains $_.Name } | ForEach-Object {
        Copy-Item $_.FullName -Destination $MiraruDestino -Recurse -Force
    }
    Remove-Item $temporal -Recurse -Force -ErrorAction SilentlyContinue
    if ($borrarZip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }

    # Datos de una instalacion anterior con el instalador .exe (carpeta AnimeTracker).
    $anterior = Join-Path $env:LOCALAPPDATA 'AnimeTracker'
    if ($primeraVez -and -not (Test-Path (Join-Path $MiraruDestino 'anime_tracker.db')) -and (Test-Path (Join-Path $anterior 'anime_tracker.db'))) {
        Miraru-Paso 'Recuperando tu lista de la instalacion anterior...'
        foreach ($f in @('anime_tracker.db', 'anime_tracker.db-wal', 'anime_tracker.db-shm', 'credentials.json')) {
            $o = Join-Path $anterior $f
            if (Test-Path $o) { Copy-Item $o -Destination $MiraruDestino -Force }
        }
    }

    # 3. Python firmado + dependencias.
    $python = $null
    if (-not $env:MIRARU_FORZAR_PYTHON) {
        Miraru-Paso 'Buscando Python 3.10 o superior...'
        $python = Miraru-BuscarPython
    }
    $propio = $false
    if (-not $python) { $python = Miraru-InstalarPython; $propio = $true }
    Miraru-Paso "Python: $python"
    if (-not (Miraru-PrepararEntorno $python)) {
        if ($propio) { throw 'No se pudieron instalar las dependencias de Miraru.' }
        # El Python que ya tenias no sirve (p. ej. demasiado nuevo para alguna dependencia):
        # se usa el oficial recomendado.
        Miraru-Paso 'Ese Python no sirve; se usara el recomendado.'
        Remove-Item (Join-Path $MiraruDestino '.venv') -Recurse -Force -ErrorAction SilentlyContinue
        $python = Miraru-InstalarPython
        if (-not (Miraru-PrepararEntorno $python)) { throw 'No se pudieron instalar las dependencias de Miraru.' }
    }

    # 4. Marca de instalacion, accesos directos y entrada en "Aplicaciones instaladas".
    $pythonw = Join-Path $MiraruDestino '.venv\Scripts\pythonw.exe'
    $vpy = Join-Path $MiraruDestino '.venv\Scripts\python.exe'
    $launcher = Join-Path $MiraruDestino 'launcher.py'
    Set-Content (Join-Path $MiraruDestino '.miraru-instalado') "install.ps1 $etiqueta" -Encoding UTF8

    if (-not $env:MIRARU_SIN_ACCESOS) {
        Miraru-Paso 'Creando accesos directos (menu Inicio y escritorio)...'
        $salida = Miraru-Nativo $vpy @((Join-Path $MiraruDestino '_acceso_directo.py'), $MiraruDestino)
        $salida | ForEach-Object { Write-Host "    $_" }

        $version = $etiqueta.TrimStart('v')
        $core = Get-Content (Join-Path $MiraruDestino 'core.py') -Raw
        if ($core -match 'VERSION\s*=\s*"([^"]+)"') { $version = $Matches[1] }
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
    }

    Write-Host ''
    Write-Host '  Miraru esta listo.' -ForegroundColor Green
    Write-Host '  Abrelo desde el menu Inicio o el escritorio. Para actualizar, vuelve a ejecutar este comando.'
    Write-Host ''
    if (-not $env:MIRARU_SIN_ABRIR) {
        Start-Process $pythonw -ArgumentList "`"$launcher`"" -WorkingDirectory $MiraruDestino
    }
}

try {
    Miraru-Instalar
} catch {
    Write-Host ''
    Write-Host "  No se pudo instalar Miraru: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Si vuelve a pasar, abre un aviso en https://github.com/$MiraruRepo/issues"
    Write-Host ''
}
