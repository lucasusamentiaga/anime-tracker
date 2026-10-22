"""Routers de dominio troceados desde main.py (Tarea 7).

Cada módulo expone `router` (APIRouter sin prefix: las rutas llevan su path
 completo, igual que en el monolito). main.py los incluye al final del
fichero porque varios módulos hacen `import main` para leer costuras.
"""

import os
import sys

# ── Costura de arranque directo (`python main.py`) ────────────────────────────
#
# Cuando main.py se ejecuta como script, Python lo registra como "__main__"
# y NO como "main". Sin este alias, el primer `import main` de los módulos de
# routes/ re-ejecutaba main.py completo como módulo "main"; esa segunda
# ejecución volvía al `from routes.animes import ...` final con el paquete
# routes a medio inicializar → ImportError circular y el servidor no llegaba
# a abrir puerto (regresión detectada por review: `uvicorn main:app`, Docker,
# y launcher.py no la sufren porque precargan "main" en sys.modules).
#
# Solo intervenimos si el __main__ en curso es main.py: en cualquier otro
# contexto (pytest, `import routes.x` suelto) "main" ya está o el propio
# `import main` del módulo lo carga limpio, sin nada a medio inicializar.
_m = sys.modules.get("__main__")
_fichero = getattr(_m, "__file__", "")
if "main" not in sys.modules and _fichero and os.path.basename(_fichero) == "main.py":
    sys.modules["main"] = _m
