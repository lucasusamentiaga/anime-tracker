' ---------------------------------------------------------------------------
'  Miraru - lanzador unico.
'
'  Doble clic aqui y la app arranca en el navegador sin ventana de consola.
'  Este archivo hace todo: busca Python, verifica la version, instala
'  dependencias si faltan y ejecuta launcher.py.
'
'  Para cerrar Miraru: boton "Salir" en el menu de la app, o cierra el
'  proceso python desde el Administrador de tareas.
'
'  Si algo falla, se muestra un cuadro de dialogo con el error y se guarda
'  detalle en arranque.log junto a este archivo.
' ---------------------------------------------------------------------------

Option Explicit

Dim fso, shell, carpeta, logFile, py, codigo, detalle

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

carpeta = fso.GetParentFolderName(WScript.ScriptFullName)
logFile = carpeta & "\arranque.log"

shell.CurrentDirectory = carpeta

' === 1. Buscar Python ========================================================
' Orden de prioridad:
'   1) venv local del proyecto
'   2) py -3 (Python Launcher for Windows)
'   3) python en PATH
'   4) python3 en PATH
'   5) AppData\Local\Programs\Python (python.org)
'   6) C:\PythonXXX (instalacion clasica)
'   7) C:\Program Files\PythonXXX
'   8) Conda / Miniconda / Anaconda / Miniforge

py = ""

' --- Prioridad 1: venv local -------------------------------------------------
If fso.FileExists(carpeta & "\venv\Scripts\python.exe") Then
    py = """" & carpeta & "\venv\Scripts\python.exe" & """"
End If

' --- Prioridad 2: py -3 (Python Launcher) ------------------------------------
If py = "" Then
    Dim rcPy
    rcPy = shell.Run("cmd /c py -3 --version >nul 2>&1", 0, True)
    If rcPy = 0 Then py = "py -3"
End If

' --- Prioridad 3: python en PATH ---------------------------------------------
If py = "" Then
    Dim rcPython
    rcPython = shell.Run("cmd /c python --version >nul 2>&1", 0, True)
    If rcPython = 0 Then py = "python"
End If

' --- Prioridad 4: python3 en PATH --------------------------------------------
If py = "" Then
    Dim rcPython3
    rcPython3 = shell.Run("cmd /c python3 --version >nul 2>&1", 0, True)
    If rcPython3 = 0 Then py = "python3"
End If

' --- Prioridad 5: AppData\Local\Programs\Python (python.org) -----------------
If py = "" Then
    Dim appLocal, versiones, v, candidato
    appLocal = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    versiones = Array("Python314", "Python313", "Python312", "Python311", _
                      "Python310", "Python39", "Python38")
    For Each v In versiones
        candidato = appLocal & "\" & v & "\python.exe"
        If fso.FileExists(candidato) Then
            py = """" & candidato & """"
            Exit For
        End If
    Next
End If

' --- Prioridad 6: C:\PythonXXX (instalacion clasica) -------------------------
If py = "" Then
    Dim rutasC, rc
    rutasC = Array("C:\Python314", "C:\Python313", "C:\Python312", _
                   "C:\Python311", "C:\Python310", "C:\Python39", "C:\Python38")
    For Each rc In rutasC
        If fso.FileExists(rc & "\python.exe") Then
            py = """" & rc & "\python.exe" & """"
            Exit For
        End If
    Next
End If

' --- Prioridad 7: C:\Program Files\PythonXXX ----------------------------------
If py = "" Then
    Dim rutasPF, rpf
    rutasPF = Array("C:\Program Files\Python314", "C:\Program Files\Python313", _
                    "C:\Program Files\Python312", "C:\Program Files\Python311", _
                    "C:\Program Files\Python310", "C:\Program Files\Python39", _
                    "C:\Program Files\Python38")
    For Each rpf In rutasPF
        If fso.FileExists(rpf & "\python.exe") Then
            py = """" & rpf & "\python.exe" & """"
            Exit For
        End If
    Next
End If

' --- Prioridad 8: Conda / Miniconda / Anaconda / Miniforge --------------------
If py = "" Then
    Dim userProfile, rutasConda, rco
    userProfile = shell.ExpandEnvironmentStrings("%USERPROFILE%")
    rutasConda = Array( _
        userProfile & "\miniconda3\python.exe", _
        userProfile & "\Miniconda3\python.exe", _
        userProfile & "\anaconda3\python.exe", _
        userProfile & "\Anaconda3\python.exe", _
        userProfile & "\miniforge3\python.exe", _
        userProfile & "\Miniforge3\python.exe", _
        "C:\ProgramData\miniconda3\python.exe", _
        "C:\ProgramData\anaconda3\python.exe", _
        "C:\tools\miniconda3\python.exe")
    For Each rco In rutasConda
        If fso.FileExists(rco) Then
            py = """" & rco & """"
            Exit For
        End If
    Next
End If

' --- No encontrado ------------------------------------------------------------
If py = "" Then
    MsgBox "No se ha encontrado Python en este equipo." & vbCrLf & vbCrLf & _
           "Instalalo desde https://www.python.org/downloads/" & vbCrLf & _
           "IMPORTANTE: marca la casilla ""Add Python to PATH"".", _
           vbCritical, "Miraru"
    WScript.Quit 1
End If


' === 2. Verificar version minima (>= 3.9) ====================================
' Sin cmd /c: shell.Run ejecuta el proceso directamente, sin problemas de
' quote-stripping que cmd /c causa con rutas que contienen espacios.
Dim rcVer
rcVer = shell.Run(py & " -c ""import sys;exit(0 if sys.version_info>=(3,9) else 1)""", 0, True)
If rcVer <> 0 Then
    MsgBox "Miraru necesita Python 3.9 o superior." & vbCrLf & vbCrLf & _
           "Actualiza Python desde https://www.python.org/downloads/", _
           vbExclamation, "Miraru"
    WScript.Quit 1
End If


' === 3. Comprobar dependencias ================================================
Dim rcDeps
rcDeps = shell.Run(py & " -c ""import fastapi,uvicorn,requests,bs4,pydantic""", 0, True)

If rcDeps <> 0 Then
    ' Instalar dependencias (ventana oculta, puede tardar 1-2 min la primera vez)
    ' cmd /c con comillas envolventes: cmd /c "todo el comando" evita el
    ' quote-stripping cuando py es una ruta con espacios entre comillas.
    Dim rcInstall
    rcInstall = shell.Run("cmd /c """ & py & " -m pip install -r """ & carpeta & _
                "\requirements.txt"" --quiet --disable-pip-version-check > """ & _
                logFile & """ 2>&1""", 0, True)
    If rcInstall <> 0 Then
        detalle = ""
        If fso.FileExists(logFile) Then
            On Error Resume Next
            detalle = vbCrLf & vbCrLf & "Detalle:" & vbCrLf & _
                      fso.OpenTextFile(logFile, 1).ReadAll()
            On Error GoTo 0
        End If
        MsgBox "No se pudieron instalar las dependencias." & vbCrLf & _
               "Comprueba tu conexion a internet y vuelve a intentarlo." & detalle, _
               vbExclamation, "Miraru"
        WScript.Quit 1
    End If
End If


' === 4. Arrancar launcher.py ==================================================
' 0 = ventana oculta.  True = esperar a que termine.
' Sin cmd /c ni redirect: launcher.py gestiona su propio log (anime_tracker.log).
' Usar cmd /c con redirect a arranque.log causaba "codigo 1" falso cuando la
' instancia anterior tenia el fichero bloqueado (sharing violation).
codigo = shell.Run(py & " """ & carpeta & "\launcher.py""", 0, True)

If codigo <> 0 Then
    ' Leer anime_tracker.log (donde launcher.py escribe sus errores)
    Dim logInterno
    logInterno = carpeta & "\anime_tracker.log"
    detalle = ""
    If fso.FileExists(logInterno) Then
        On Error Resume Next
        detalle = vbCrLf & vbCrLf & "Detalle:" & vbCrLf & _
                  fso.OpenTextFile(logInterno, 1).ReadAll()
        On Error GoTo 0
    End If
    MsgBox "Miraru no pudo arrancar (codigo " & codigo & ")." & detalle, _
           vbExclamation, "Miraru"
End If
