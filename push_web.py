"""
push_web.py — Notificaciones Web Push (llegan aunque la pestaña esté cerrada).

Flujo:
  1. La página pide la clave pública VAPID (clave_publica) y suscribe su
     Service Worker con pushManager.subscribe().
  2. Envía la suscripción a /api/push/subscribe → se guarda en config.
  3. El daemon de notificaciones llama a enviar() cuando hay episodio nuevo:
     el servicio de push del navegador (FCM en Chrome, Mozilla en Firefox)
     despierta al Service Worker, que muestra el aviso.

Requisitos: que el servidor de Miraru esté corriendo (es quien envía) y un
contexto seguro en el navegador (http://127.0.0.1 lo es; una IP de la LAN por
http no, así que el móvil por WiFi no puede suscribirse).

Si pywebpush no está instalado, todo devuelve "no disponible" sin romper nada.
"""
from __future__ import annotations

import base64
import json
import logging
import threading

import database as db

log = logging.getLogger("miraru.push")

_CFG_CLAVE = "push_vapid_pem"
_CFG_SUBS = "push_subs"
_MAX_SUBS = 20
_lock = threading.Lock()

try:  # dependencia opcional
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01 as _Vapid
    from pywebpush import webpush
    DISPONIBLE = True
except Exception:  # pragma: no cover - depende del entorno
    DISPONIBLE = False


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _vapid():
    """Instancia Vapid con la clave guardada (la genera la primera vez)."""
    with _lock:
        pem = db.get_config(_CFG_CLAVE)
        if pem:
            return _Vapid.from_pem(pem.encode("ascii"))
        v = _Vapid()
        v.generate_keys()
        db.set_config(_CFG_CLAVE, v.private_pem().decode("ascii"))
        return v


def clave_publica() -> str | None:
    """applicationServerKey en base64url (punto EC sin comprimir), o None."""
    if not DISPONIBLE:
        return None
    raw = _vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64url(raw)


def _leer_subs() -> list[dict]:
    try:
        subs = json.loads(db.get_config(_CFG_SUBS) or "[]")
        return [s for s in subs if isinstance(s, dict) and s.get("endpoint")]
    except Exception:
        return []


def _guardar_subs(subs: list[dict]) -> None:
    db.set_config(_CFG_SUBS, json.dumps(subs[-_MAX_SUBS:]))


def validar(sub: dict) -> bool:
    keys = (sub or {}).get("keys") or {}
    endpoint = (sub or {}).get("endpoint") or ""
    return (endpoint.startswith("https://") and len(endpoint) < 2048
            and bool(keys.get("p256dh")) and bool(keys.get("auth")))


def suscribir(sub: dict) -> bool:
    if not validar(sub):
        return False
    limpia = {"endpoint": sub["endpoint"],
              "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}}
    with _lock:
        subs = [s for s in _leer_subs() if s["endpoint"] != limpia["endpoint"]]
        subs.append(limpia)
        _guardar_subs(subs)
    return True


def desuscribir(endpoint: str) -> bool:
    with _lock:
        subs = _leer_subs()
        nuevas = [s for s in subs if s["endpoint"] != endpoint]
        _guardar_subs(nuevas)
    return len(nuevas) != len(subs)


def num_suscripciones() -> int:
    return len(_leer_subs())


def enviar(titulo: str, cuerpo: str = "", url: str = "/app",
           tag: str | None = None, icono: str | None = None,
           _webpush=None) -> tuple[int, int]:
    """Envía a todas las suscripciones. Devuelve (enviadas, eliminadas).

    Las que el servicio de push da por caducadas (404/410) se borran."""
    if not DISPONIBLE and _webpush is None:
        return 0, 0
    enviar_fn = _webpush or webpush
    payload = json.dumps({"title": titulo[:120], "body": cuerpo[:300], "url": url,
                          "tag": tag, "icon": icono or "/static/logo.png"})
    remitente = db.get_config("email_notif") or "noreply@miraru.app"
    claims = {"sub": f"mailto:{remitente}"}
    vapid = _vapid() if _webpush is None else None
    ok = 0
    caducadas: list[str] = []
    for s in _leer_subs():
        try:
            enviar_fn(subscription_info=s, data=payload, vapid_private_key=vapid,
                      vapid_claims=dict(claims), timeout=10)
            ok += 1
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                caducadas.append(s["endpoint"])
            else:
                log.warning("push fallido (%s): %s", status, str(e)[:200])
    for ep in caducadas:
        desuscribir(ep)
    return ok, len(caducadas)
