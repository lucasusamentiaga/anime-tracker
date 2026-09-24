"""
Sincronización con Google Sheets — limpio, sin colores, sin sinopsis.
"""
from __future__ import annotations

import re
from pathlib import Path

# Google libraries — lazy import (heavy, only loaded when Sheets is used)
_google_libs_loaded = False

def _load_google():
    global _google_libs_loaded, service_account, build
    if not _google_libs_loaded:
        from google.oauth2 import service_account as _sa
        from googleapiclient.discovery import build as _build
        service_account = _sa
        build = _build
        _google_libs_loaded = True

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Columnas que se exportan (sin imagen ni sinopsis)
# Orden canónico — debe coincidir exactamente con el CSV export
HEADERS_DB = [
    "nombre", "fuente", "capitulos", "genero",
    "estado_anime", "estado_usuario", "puntuacion",
    "episodios_vistos", "temporada", "lista_personalizada",
    "favorito", "notif_activa", "fecha_inicio", "fecha_fin", "notas",
]

HEADERS_DISPLAY = [
    "📺 Nombre", "🔍 Fuente", "📊 Capítulos", "🎭 Géneros",
    "📡 Estado anime", "👤 Mi estado", "⭐ Puntuación",
    "▶ Eps vistos", "🗓 Temporada", "📂 Lista",
    "⭐ Fav", "🔔 Notif", "📅 Inicio", "📅 Fin", "📌 Notas",
]

COL_WIDTHS = [220, 90, 80, 160, 110, 100, 85, 75, 100, 90, 40, 40, 90, 90, 200]

def _service(spreadsheet_id: str, credentials_path: str):
    _load_google()
    creds_file = Path(credentials_path)
    if not creds_file.exists():
        raise FileNotFoundError(
            f"No se encontró credentials.json en:\n{credentials_path}\n\n"
            "Ve a Configuración y vuelve a subir credentials.json."
        )
    creds = service_account.Credentials.from_service_account_file(
        str(creds_file), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False), spreadsheet_id

def _get_sheet_info(svc, sid: str) -> tuple[str, int]:
    try:
        meta  = svc.spreadsheets().get(spreadsheetId=sid).execute()
        props = meta["sheets"][0]["properties"]
        return props["title"], props["sheetId"]
    except Exception:
        return "Sheet1", 0

def _row(anime: dict) -> list:
    return [str(anime.get(h) or "") for h in HEADERS_DB]

# Paleta de colores — degradado suave morado→blanco
_HDR_BG  = {"red": 0.486, "green": 0.302, "blue": 0.890}   # morado vibrante #7C3AE3
_HDR_FG  = {"red": 1.0,   "green": 1.0,   "blue": 1.0}     # blanco puro
_ROW_ODD = {"red": 0.961, "green": 0.949, "blue": 0.988}   # lila muy claro #F5EDFC
_ROW_EVN = {"red": 0.988, "green": 0.984, "blue": 0.996}   # casi blanco #FCFAFF
_TXT     = {"red": 0.133, "green": 0.094, "blue": 0.259}   # morado oscuro #221860
_NAME_FG = {"red": 0.404, "green": 0.149, "blue": 0.780}   # acento morado #671DC7

def _fmt_requests(sheet_id: int, n_rows: int) -> list:
    reqs = []

    # ── Cabecera: morado vibrante, texto blanco, negrita ──────────────────
    reqs.append({"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": _HDR_BG,
            "textFormat": {
                "foregroundColor": _HDR_FG,
                "bold": True,
                "fontSize": 11,
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
    }})

    # ── Filas de datos: alternancia lila claro / casi blanco ──────────────
    if n_rows > 0:
        for i in range(n_rows):
            bg = _ROW_ODD if i % 2 == 0 else _ROW_EVN
            reqs.append({"repeatCell": {
                "range": {"sheetId": sheet_id,
                          "startRowIndex": i + 1, "endRowIndex": i + 2},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": bg,
                    "textFormat": {"foregroundColor": _TXT, "fontSize": 10},
                    "verticalAlignment": "MIDDLE",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
            }})

        # Nombre (col A) en color acento + negrita
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows + 1,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": _NAME_FG, "bold": True, "fontSize": 10},
            }},
            "fields": "userEnteredFormat.textFormat",
        }})

        # Columnas centradas: fuente(1), capitulos(2), estado_anime(4), estado_usuario(5),
        # puntuacion(6), eps_vistos(7), temporada(8), lista(9), fav(10), notif(11),
        # fecha_inicio(12), fecha_fin(13)
        center_cols = [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        for ci in center_cols:
            reqs.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows + 1,
                          "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }})
    # Anchos de columna
    for ci, w in enumerate(COL_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": ci, "endIndex": ci + 1},
            "properties": {"pixelSize": w},
            "fields": "pixelSize",
        }})
    # Alto cabecera
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 32},
        "fields": "pixelSize",
    }})
    # Alto filas datos
    if n_rows > 0:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": 1, "endIndex": n_rows + 1},
            "properties": {"pixelSize": 22},
            "fields": "pixelSize",
        }})
    # Freeze fila 1
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount",
    }})
    return reqs

def verificar_credenciales(spreadsheet_id: str, credentials_path: str) -> tuple[bool, str]:
    try:
        svc, sid = _service(spreadsheet_id, credentials_path)
        svc.spreadsheets().get(spreadsheetId=sid).execute()
        return True, "ok"
    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        msg = str(e)
        if "404" in msg: return False, "Hoja no encontrada. Comprueba el ID en la URL."
        if "403" in msg: return False, "Sin permisos. Comparte la hoja con el email de la cuenta de servicio."
        if "invalid_grant" in msg or "401" in msg: return False, "Credenciales inválidas. Vuelve a descargar credentials.json."
        return False, f"Error: {msg[:200]}"

def sincronizar_todo(animes: list[dict], spreadsheet_id: str, credentials_path: str) -> tuple[bool, str]:
    try:
        svc, sid = _service(spreadsheet_id, credentials_path)
        sheet_name, sheet_id = _get_sheet_info(svc, sid)
        rows = [HEADERS_DISPLAY] + [_row(a) for a in animes]
        svc.spreadsheets().values().clear(spreadsheetId=sid, range=sheet_name).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED", body={"values": rows},
        ).execute()
        fmts = _fmt_requests(sheet_id, len(animes))
        if fmts:
            svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": fmts}).execute()
        return True, f"{len(animes)} animes sincronizados"
    except Exception as e:
        return False, str(e)[:300]

def append_anime(anime: dict, spreadsheet_id: str, credentials_path: str) -> tuple[bool, str]:
    try:
        svc, sid = _service(spreadsheet_id, credentials_path)
        sheet_name, sheet_id = _get_sheet_info(svc, sid)
        existing = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{sheet_name}!A1:A1"
        ).execute()
        first_time = "values" not in existing
        rows = ([HEADERS_DISPLAY] if first_time else []) + [_row(anime)]
        result = svc.spreadsheets().values().append(
            spreadsheetId=sid, range=sheet_name,
            valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        fmts = []
        if first_time:
            fmts += _fmt_requests(sheet_id, 1)
        else:
            updated = result.get("updates", {}).get("updatedRange", "")
            m = re.search(r":?[A-Z]+(\d+)$", updated)
            if m:
                ri = int(m.group(1)) - 1   # índice de fila 0-based (cabecera = 0)
                if ri >= 1:
                    # Misma estética que el resto: alternancia lila/blanco + texto
                    # oscuro (antes pintaba la fila en tema oscuro y desentonaba).
                    data_idx = ri - 1
                    bg = _ROW_ODD if data_idx % 2 == 0 else _ROW_EVN
                    fmts.append({"repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": ri, "endRowIndex": ri + 1},
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": bg,
                            "textFormat": {"foregroundColor": _TXT, "fontSize": 10},
                            "verticalAlignment": "MIDDLE",
                        }},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
                    }})
                    # Nombre (col A) en acento morado + negrita, como en el sync completo
                    fmts.append({"repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": ri, "endRowIndex": ri + 1,
                                  "startColumnIndex": 0, "endColumnIndex": 1},
                        "cell": {"userEnteredFormat": {
                            "textFormat": {"foregroundColor": _NAME_FG, "bold": True, "fontSize": 10},
                        }},
                        "fields": "userEnteredFormat.textFormat",
                    }})
        if fmts:
            svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": fmts}).execute()
        return True, "ok"
    except Exception as e:
        return False, str(e)[:300]

def update_anime_row(anime: dict, spreadsheet_id: str, credentials_path: str) -> tuple[bool, str]:
    try:
        svc, sid = _service(spreadsheet_id, credentials_path)
        sheet_name, _ = _get_sheet_info(svc, sid)
        all_vals = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{sheet_name}!A:A"
        ).execute().get("values", [])
        row_idx = next((i for i, r in enumerate(all_vals) if r and r[0] == anime.get("nombre")), None)
        if row_idx is None:
            return False, "no encontrado en Sheets"
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{sheet_name}!A{row_idx + 1}",
            valueInputOption="USER_ENTERED", body={"values": [_row(anime)]},
        ).execute()
        return True, "ok"
    except Exception as e:
        return False, str(e)[:300]

def delete_anime_row(nombre: str, spreadsheet_id: str, credentials_path: str) -> tuple[bool, str]:
    try:
        svc, sid = _service(spreadsheet_id, credentials_path)
        sheet_name, sheet_id = _get_sheet_info(svc, sid)
        all_vals = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{sheet_name}!A:A"
        ).execute().get("values", [])
        row_idx = next((i for i, r in enumerate(all_vals) if r and r[0] == nombre), None)
        if row_idx is None:
            return False, "no encontrado en Sheets"
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
            {"deleteDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS",
                                           "startIndex": row_idx, "endIndex": row_idx + 1}}}
        ]}).execute()
        return True, "ok"
    except Exception as e:
        return False, str(e)[:300]
